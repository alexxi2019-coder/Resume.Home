"""Local, conservative resume extraction. Content is always data, never instructions."""
import base64
import difflib
import io
import json
import re
import subprocess
import sys
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_FILE = 10 * 1024 * 1024
MAX_TEXT = 250000
MAX_PAGES = 50
ROOT = Path(__file__).resolve().parent
NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


class ResumeError(ValueError):
    pass


def _xml(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ResumeError('DOCX XML declarations with entities are not supported.')
    return ET.fromstring(raw)


def docx_lines(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            entries = z.infolist()
            if len(entries) > 2000 or sum(f.file_size for f in entries) > 30*1024*1024:
                raise ResumeError('DOCX expands beyond the 30 MB safety limit.')
            names = z.namelist()
            if len(names) != len(set(names)) or 'word/document.xml' not in names or '[Content_Types].xml' not in names:
                raise ResumeError('This is not a valid DOCX document.')
            types = z.read('[Content_Types].xml')
            if b'macroEnabled' in types or any('vbaproject' in n.lower() for n in names):
                raise ResumeError('Macro-enabled documents are not accepted. Save a plain DOCX or paste text.')
            document = _xml(z.read('word/document.xml'))
            list_styles = set()
            if 'word/styles.xml' in names:
                styles = _xml(z.read('word/styles.xml'))
                list_styles = {s.get(NS+'styleId') for s in styles.findall(NS+'style') if s.find('.//'+NS+'numPr') is not None}
            body = document.find(NS+'body')
            if body is None:
                raise ResumeError('The DOCX has no document body.')
            out = []
            # Iteration includes table cells, in document order. Layout association remains reviewable.
            for n,p in enumerate(body.iter(NS+'p'), 1):
                chunks = []
                for child in p.iter():
                    if child.tag == NS+'t':
                        chunks.append(child.text or '')
                    elif child.tag == NS+'tab':
                        chunks.append('\t')
                    elif child.tag in (NS+'br',NS+'cr'):
                        chunks.append('\n')
                content = ''.join(chunks).strip()
                style = p.find('./'+NS+'pPr/'+NS+'pStyle')
                numbered = p.find('./'+NS+'pPr/'+NS+'numPr') is not None or (style is not None and style.get(NS+'val') in list_styles)
                for i,line in enumerate(content.splitlines() or ['']):
                    out.append({'text':line, 'location':'Paragraph '+str(n), 'list_item':numbered and i==0})
            return out, ['DOCX paragraphs and table cells are read in document order; review multi-column associations. Page numbers are unavailable in DOCX.']
    except ResumeError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, OSError):
        raise ResumeError('The DOCX is damaged, encrypted, or not a supported Word document. Try saving it again or paste its text.')


def pdf_lines(raw):
    sys.path.insert(0, str(ROOT/'vendor'/'pdf-deps.zip'))
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise ResumeError('Password-protected PDFs are not supported. Upload an unencrypted copy or paste the resume text.')
        if len(reader.pages) > MAX_PAGES:
            raise ResumeError('PDF exceeds the 50-page limit.')
        out, empty_pages = [], []
        for n,page in enumerate(reader.pages,1):
            content = page.extract_text() or ''
            if not re.search(r'\w',content):
                empty_pages.append(n)
            for line in content.splitlines():
                out.append({'text':line,'location':'Page '+str(n),'list_item':False})
        if not out or all(not x['text'].strip() for x in out):
            raise ResumeError('No text could be extracted. This may be a scanned/image-only PDF. OCR is not installed in this app. Use OCR in your PDF software, then upload the searchable PDF, or choose Paste text.')
        warnings = ['PDF reading order can differ from its visual layout. Review columns, wrapped lines, and role associations.']
        if empty_pages:
            warnings.append('No text on pages '+', '.join(map(str,empty_pages))+'. OCR is not supported; paste any missing text before importing.')
        return out, warnings
    except ResumeError:
        raise
    except Exception:
        raise ResumeError('Could not read this PDF. It may be damaged or use unsupported text encoding. Try a DOCX or paste the text.')


def extract_input(data):
    if data.get('kind') == 'text':
        content = data.get('text')
        if not isinstance(content,str) or not content.strip():
            raise ResumeError('Paste your resume text first.')
        if len(content) > MAX_TEXT:
            raise ResumeError('Pasted text exceeds the 250,000-character limit.')
        return 'Pasted resume text', [{'text':s,'location':'Line '+str(i),'list_item':False} for i,s in enumerate(content.splitlines(),1)], []
    if data.get('kind') != 'file':
        raise ResumeError('Choose a PDF, DOCX, or pasted text.')
    filename = data.get('filename')
    if not isinstance(filename,str) or not filename or len(filename)>255 or '\x00' in filename:
        raise ResumeError('Invalid source filename.')
    filename = filename.replace('\\','/').split('/')[-1]
    ext = Path(filename).suffix.lower()
    if ext not in ('.pdf','.docx'):
        raise ResumeError('Only PDF and DOCX files are accepted. For other formats, paste text.')
    encoded = data.get('content_base64')
    if not isinstance(encoded,str) or len(encoded)>((MAX_FILE+2)//3)*4:
        raise ResumeError('File exceeds the 10 MB limit.')
    try:
        raw = base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError):
        raise ResumeError('The upload is not valid base64 data.')
    if not raw or len(raw)>MAX_FILE:
        raise ResumeError('The file is empty or exceeds the 10 MB limit.')
    if ext=='.pdf':
        if not raw.startswith(b'%PDF-'):
            raise ResumeError('File contents do not match a PDF. Renaming a file is not conversion.')
        lines,warnings = pdf_lines(raw)
    else:
        if not raw.startswith(b'PK\x03\x04'):
            raise ResumeError('File contents do not match a DOCX. Upload a Word .docx or paste text.')
        lines,warnings = docx_lines(raw)
    if sum(len(x['text']) for x in lines)>MAX_TEXT:
        raise ResumeError('Extracted text exceeds the 250,000-character limit.')
    return filename, lines, warnings


SECTIONS = {
    'experience': r'(?:work|professional|relevant|employment|career|industry)?\s*(?:experience|history)|employment',
    'projects': r'(?:selected|personal|relevant|technical|academic)?\s*projects',
    'education': r'education(?:\s*(?:and|&)\s*qualifications)?|academic background',
    'certifications': r'certifications?(?:\s*(?:and|&)\s*(?:licenses|leadership))?|licenses(?:\s*(?:and|&)\s*certifications)?',
    'summary': r'(?:professional|career|executive)?\s*(?:summary|profile)|about me|objective',
    'skills': r'(?:technical|core|key|professional)?\s*(?:skills|competencies)|technologies',
    'interests': r'(?:personal\s+)?interests|hobbies(?:\s*(?:and|&)\s*interests)?',
    'other': r'awards|languages|publications|references|volunteering|volunteer experience',
    'contact': r'contact(?: details| information)?',
}
ROLE = re.compile(r'\b(?:engineer|analyst|manager|developer|designer|director|consultant|specialist|associate|intern|researcher|scientist|architect|officer|founder|coordinator|administrator|accountant|president|head|lead|assistant|technician|supervisor|writer|editor|recruiter|representative)\b', re.I)
ACTION = re.compile(r'^(?:built|led|managed|created|developed|designed|implemented|automated|improved|reduced|increased|delivered|launched|achieved|supported|conducted|analyzed|analysed|partnered|collaborated|optimized|optimised|drove|maintained|saved|trained|mentored|oversaw|resolved|established|negotiated|produced|coordinated|processed)\b', re.I)
MONTH = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?'
DATE = r'(?:'+MONTH+r'\s+(?:19|20)\d{2}|(?:0?[1-9]|1[0-2])/(?:19|20)\d{2}|(?:19|20)\d{2}(?:-\d{2}(?:-\d{2})?)?|Present|Current|Now)'
DATE_RANGE = re.compile(r'(?<!\w)'+DATE+r'\s*(?:[–—-]|\bto\b)\s*'+DATE+r'(?!\w)',re.I)
BULLET = re.compile(r'^\s*(?:[•●▪◦‣∙\uf0b7*]\s*|\x7f\s+|[-–]\s+|\d+[.)]\s+)')
SKILLS = ['Python','SQL','JavaScript','TypeScript','Java','C++','C#','Go','Rust','R','HTML','CSS','React','Node.js','Excel','Tableau','Power BI','Salesforce','AWS','Azure','GCP','Docker','Kubernetes','PostgreSQL','MySQL','Git','Figma','Jira','SAP','MATLAB','TensorFlow','PyTorch','SEO','A/B testing','machine learning','data analysis','project management','Agile','Scrum']


def suggest_tags(bullet):
    # Only names present in the bullet; no inference from employer, role, or a skills section.
    return [s for s in SKILLS if re.search(r'(?<![\w+#])'+re.escape(s)+r'(?![\w+#])',bullet,re.I)]


def section_name(s):
    normalized = s.strip().rstrip(':').strip()
    for name,pattern in SECTIONS.items():
        if re.fullmatch(pattern,normalized,re.I):
            return name
    return None


def clean_heading(s):
    return s.strip(' \t|,–—-')


def parse_header(headers, previous, section):
    group = {'employer':'','role':'','employment_dates':'','project':'','warnings':[]}
    pieces = []
    for h in headers:
        dates = DATE_RANGE.search(h)
        if dates:
            if group['employment_dates'] and group['employment_dates'] != dates.group():
                group['warnings'].append('Multiple date ranges in this header; check dates.')
            group['employment_dates'] = dates.group()
            h = h[:dates.start()]+h[dates.end():]
        explicit = re.match(r'^(Employer|Company|Role|Title|Project)\s*:\s*(.+)$',h,re.I)
        if explicit:
            key = {'employer':'employer','company':'employer','role':'role','title':'role','project':'project'}[explicit[1].lower()]
            group[key] = clean_heading(explicit[2])
            continue
        for p in re.split(r'\s*[|\t]\s*|\s{2,}|\s+[–—]\s+',h):
            p = clean_heading(p)
            if p: pieces.append(p)
    for p in pieces[:]:
        m = re.match(r'^(.+?)\s+(?:at|@)\s+(.+)$',p,re.I)
        if m and ROLE.search(m[1]):
            group['role'],group['employer']=m[1],m[2]
            pieces.remove(p)
    roles = [p for p in pieces if ROLE.search(p)]
    nonroles = [p for p in pieces if p not in roles]
    if not group['role'] and roles:
        group['role']=roles[0]
        if len(roles)>1: group['warnings'].append('Several possible titles found; verify the role.')
    if not group['employer'] and nonroles and section!='projects':
        group['employer']=nonroles[0]
        if len(nonroles)>1:group['warnings'].append('Additional header text may be a location or employer; verify association.')
    if not group['employer'] and group['role'] and previous and section!='projects':
        group['employer']=previous['employer']
        group['warnings'].append('Employer carried from previous role; verify this association.')
    if section=='projects' and not group['project'] and nonroles:
        group['project']=nonroles[0]
    if not group['employer']:group['warnings'].append('Employer missing; enter it or move the bullet before importing.')
    if not group['role']:group['warnings'].append('Role missing; enter it or move the bullet before importing.')
    if not group['employment_dates']:group['warnings'].append('Employment dates not identified; leave blank if unknown.')
    group['source_header']='\n'.join(headers)
    return group


def parse_resume(lines):
    groups,items,separate = [],[],[]
    section='contact'; explicit_section=False; pending=[]; current=None; active=None; project=''

    def flush():
        nonlocal active
        if active:
            active['original_text']=active['bullet']
            active['tags']=suggest_tags(active['bullet'])
            active['source_location']='; '.join(dict.fromkeys(active.pop('locations')))+' · '+active['section']
            items.append(active)
            active=None

    def make_group():
        nonlocal current,pending,project
        g=parse_header(pending,current,section)
        g['id']='role-'+str(len(groups)+1)
        groups.append(g); current=g; pending=[]; project=g['project']

    for index,line in enumerate(lines):
        raw=line['text']; s=raw.strip()
        if not s:
            continue
        heading=section_name(s)
        if heading:
            flush()
            separate.extend({'section':'unclassified','text':p,'source_location':'Unassigned header'} for p in pending)
            pending=[];current=None;project='';section=heading;explicit_section=True
            continue
        upcoming = [x['text'].strip() for x in lines[index+1:index+5] if x['text'].strip()]
        next_text = upcoming[0] if upcoming else ''
        marked=bool(BULLET.match(s) or line.get('list_item'))
        # When there is no section heading, recognize a conservative employer/title header pair.
        if section=='contact' and not explicit_section and not marked and not ACTION.match(s) and (ROLE.search(s) or DATE_RANGE.search(s) or (ROLE.search(next_text) and len(s.split())<12)):
            section='experience'
        if section not in ('experience','projects'):
            separate.append({'section':section,'text':raw,'source_location':line['location']})
            continue
        # Embedded labeled exclusions never become accomplishments.
        if re.match(r'^(?:Education|Certifications?|Summary|Contact|Skills)\s*:',s,re.I):
            flush(); separate.append({'section':'other','text':raw,'source_location':line['location']});continue
        project_match=re.match(r'^Projects?\s*:\s*(.+)',s,re.I)
        if project_match:
            flush()
            if pending or current is None:make_group()
            project=project_match[1].strip();continue
        is_action=bool(ACTION.match(s))
        # Employers can precede a location line and then a title/date pair.
        upcoming_header=[]
        for candidate in upcoming:
            if BULLET.match(candidate) or section_name(candidate):break
            upcoming_header.append(candidate)
        employer_heading = (s[:1].isupper() and len(s.split())<=10 and not s.endswith(';')
                            and (not s.endswith('.') or bool(re.search(r'\b(?:Co|Inc|Ltd|Corp)\.$',s)))
                            and any(ROLE.search(h) and not ACTION.match(h) for h in upcoming_header))
        project_heading = (section=='projects' and not marked and not is_action and s[:1].isupper()
                           and len(s.split())<=12 and bool(BULLET.match(next_text)))
        if project_heading:
            flush();pending=[s];current=None;project='';continue
        header = not marked and not is_action and (
            bool(DATE_RANGE.search(s)) or
            (bool(ROLE.search(s)) and len(s.split())<=14 and not s.endswith(('.', ';'))) or
            bool(re.match(r'^(?:Employer|Company|Role|Title)\s*:',s,re.I)) or
            employer_heading or
            (len(s.split())<=12 and not s.endswith(('.', ';')) and bool(ROLE.search(next_text) or DATE_RANGE.search(next_text)))
        )
        if header:
            flush();pending.append(s);continue
        new_action = is_action and (active is None or (active['bullet'].endswith(('.', '!', '?')) and not raw[:1].isspace()))
        if marked or new_action:
            flush()
            if pending or current is None:make_group()
            wording=BULLET.sub('',s,count=1) if marked else s
            active={'id':'bullet-'+str(len(items)+1),'group_id':current['id'],'bullet':wording,'project':project,
                    'section':section,'locations':[line['location']], 'warnings':[] if marked else ['Unmarked action sentence treated as a bullet; review its boundaries.']}
            continue
        if active:
            # Do not hyphenate or dehyphenate words: joining wraps preserves punctuation and metrics.
            active['bullet']+=' '+s
            active['locations'].append(line['location'])
        elif section=='projects':
            pending.append(s)
        elif not current:
            pending.append(s)
        else:
            separate.append({'section':'unclassified','text':raw,'source_location':line['location']})
    flush()
    if pending:
        separate.extend({'section':'unclassified','text':p,'source_location':'Unassigned header'} for p in pending)
    if len(items)>300:
        raise ResumeError('More than 300 bullet candidates found. Split the resume into smaller imports.')
    return {'groups':groups,'items':items,'separate':separate}


def normalized(s):
    return ' '.join(unicodedata.normalize('NFKC',s).casefold().split())


def duplicate_candidates(bullet, versions):
    target=normalized(bullet); output=[]; seen=set()
    ranked=[]
    for v in versions:
        other=normalized(v['bullet'])
        if not target or not other:continue
        exact=target==other
        # Conservatively surface wording with changed metrics as likely duplicates, not exact.
        score=difflib.SequenceMatcher(None,target,other,autojunk=False).ratio()
        if exact or (min(len(target),len(other))>=20 and score>=.78):
            ranked.append((exact,score,v))
    for exact,score,v in sorted(ranked,key=lambda r:(r[0],r[1],r[2]['number']),reverse=True):
        if v['accomplishment_id'] in seen:continue
        seen.add(v['accomplishment_id'])
        output.append({'version_id':v['id'],'accomplishment_id':v['accomplishment_id'],'number':v['number'],
                       'kind':'exact' if exact else 'likely','similarity':round(score*100),'bullet':v['bullet'],'employer':v['employer'],'role':v['role']})
    return output[:10]


def extract_preview(data):
    filename,lines,warnings=extract_input(data)
    parsed=parse_resume(lines)
    extend_profile_sections(parsed)
    if not parsed['items']:
        warnings.append('No accomplishment bullets identified. Review the extracted text, then paste it with explicit employer, role, and bullet lines.')
    return dict(parsed,source_filename=filename,warnings=warnings,extracted_text='\n'.join(x['text'] for x in lines))


def extend_profile_sections(parsed):
    """Promote explicit resume sections to reviewable entries without inferring credentials."""
    for g in parsed['groups']:
        members=[i for i in parsed['items'] if i['group_id']==g['id']]
        g['category']='project' if members and members[0]['section']=='projects' else 'experience'
        g['title']=g['project'] if g['category']=='project' else ''
        if g['category']=='project':
            g['warnings']=[w for w in g['warnings'] if not w.startswith(('Employer missing','Role missing','Employment dates'))]
            if not g['title']:g['warnings'].append('Project name missing; add it before importing.')
        for i in members:
            i['category']=g['category'];i['title']=g['title']
    remaining=[];blocks=[];active=None
    categories={'education':'education','skills':'skill','certifications':'certification','interests':'interest'}
    for row in parsed['separate']:
        for part in re.split(r'\s*\|\s*(?=(?:Interests|Languages):)',row['text']):
            section=row['section']
            explicit=re.match(r'\s*(Interests|Languages|Certifications?)\s*:',part,re.I)
            if explicit:
                section={'interests':'interests','languages':'skills','certification':'certifications','certifications':'certifications'}[explicit[1].lower()]
            if section=='certifications' and re.search(r'Vice President|organized|networking events',part,re.I):
                section='other'
            category=categories.get(section)
            if not category:
                remaining.append(dict(row,text=part));active=None;continue
            label=re.match(r'^\s*([A-Za-z &/]+):',part)
            starts=bool(label or BULLET.match(part))
            if active is None or active['category']!=category or starts:
                active={'category':category,'rows':[],'label':label[1] if label else ''}
                blocks.append(active)
            active['rows'].append(dict(row,text=part))
    for n,block in enumerate(blocks,1):
        category=block['category'];rows=block['rows']
        wording=' '.join(BULLET.sub('',r['text'].strip(),count=1) for r in rows)
        first=BULLET.sub('',rows[0]['text'].strip(),count=1)
        title=block['label'] or first
        employer=''
        if category=='education':
            if re.search(r'University|College|School|Institute',first,re.I):employer=first
            title=next((r['text'].strip() for r in rows if re.search(r'Bachelor|Master|Doctor|Diploma|BSc|MSc|B\.S\.|M\.S\.|Ph\.?D',r['text'],re.I)),first)
        gid='profile-role-'+str(n);iid='profile-entry-'+str(n)
        dates=next((r['text'].strip() for r in rows if re.fullmatch(DATE,r['text'].strip(),re.I) or DATE_RANGE.fullmatch(r['text'].strip())), '')
        parsed['groups'].append({'id':gid,'category':category,'title':title,'employer':employer,'role':'','project':'','employment_dates':dates,
                                 'source_header':first,'warnings':['Section text preserved as an entry. Review its title, dates, and classification; split multiple qualifications if needed.']})
        parsed['items'].append({'id':iid,'group_id':gid,'category':category,'title':title,'bullet':wording,'original_text':wording,'project':'',
                                'tags':suggest_tags(wording),'section':category,'source_location':'; '.join(dict.fromkeys(r['source_location'] for r in rows)), 'warnings':[]})
    parsed['separate']=remaining
    if len(parsed['items'])>300:raise ResumeError('More than 300 entries found. Split the resume into smaller imports.')


def isolated_preview(data):
    """Bound parser runtime; uploads never touch disk and worker is always reaped."""
    try:
        command=[sys.executable,'--resume-worker'] if getattr(sys,'frozen',False) else [sys.executable,'-B',str(Path(__file__).resolve()),'--worker']
        result=subprocess.run(command,input=json.dumps(data),capture_output=True,text=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired:
        raise ResumeError('Extraction exceeded 20 seconds. Try a simpler DOCX or paste the resume text.')
    if result.returncode:
        raise ResumeError('The document exceeded extraction limits or could not be read. Try paste text.')
    try: payload=json.loads(result.stdout)
    except ValueError:raise ResumeError('Extraction could not finish. Try paste text.')
    if 'error' in payload:raise ResumeError(payload['error'])
    return payload


if __name__=='__main__':
    try:
        # Resource limits affect only this isolated parsing process, not the app server.
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU,(15,15))
            resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
        except (ImportError,ValueError,OSError):
            pass
        print(json.dumps(extract_preview(json.load(sys.stdin))))
    except ResumeError as exc:
        print(json.dumps({'error':str(exc)}))
    except Exception:
        print(json.dumps({'error':'Document extraction failed. Try a plain DOCX or paste text.'}))
