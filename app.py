#!/usr/bin/env python3
"""Local resume library. Python 3.9+, no third-party dependencies."""
import argparse
import datetime as dt
import difflib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote
from resume_parser import isolated_preview, duplicate_candidates, ResumeError

ROOT = Path(__file__).resolve().parent
LABELS = ('strong evidence', 'partial evidence', 'no evidence')


class ValidationError(Exception):
    pass


def uid():
    return str(uuid.uuid4())


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def text(value, name, required=False, limit=30000):
    if not isinstance(value, str):
        raise ValidationError(name + ' must be text.')
    value = value.strip()
    if required and not value:
        raise ValidationError(name + ' is required.')
    if len(value) > limit:
        raise ValidationError(name + ' is too long.')
    return value


def choice(value, values, name):
    if value not in values:
        raise ValidationError('Invalid ' + name + '.')
    return value


STOP = set('a an the and or of to in for with on at by as is are be have has from this that you we our your will must should required preferred requirements qualifications experience knowledge ability skills skill using use years year minimum plus strong excellent demonstrated proven'.split())
# A deliberately small, inspectable concept dictionary, not an embedding model.
CONCEPTS = {
    'leadership': ['leadership', 'led', 'lead', 'managed', 'managing', 'supervised'],
    'collaboration': ['collaboration', 'collaborated', 'partnered', 'teamwork', 'cross-functional'],
    'automation': ['automation', 'automated', 'automating'],
    'analysis': ['analysis', 'analytics', 'analyzed', 'analysed', 'analyzing'],
    'communication': ['communication', 'communicated', 'presented', 'presentations'],
    'optimization': ['optimization', 'optimized', 'optimised', 'improved', 'improvement'],
    'development': ['development', 'developed', 'built', 'implemented'],
    'customer': ['customer', 'customers', 'client', 'clients'],
    'salesforce': ['salesforce', 'sfdc'],
    'javascript': ['javascript', 'js'],
    'postgresql': ['postgresql', 'postgres'],
    'aws': ['aws', 'amazon web services'],
    'machinelearning': ['machine learning', 'ml'],
}


def tokens(s, semantic=False):
    s = s.lower()
    if semantic:
        for concept, aliases in CONCEPTS.items():
            for alias in sorted(aliases, key=len, reverse=True):
                s = re.sub(r'(?<![\w+#])' + re.escape(alias) + r'(?![\w+#])', concept, s)
    return set(re.findall(r'[a-z0-9]+(?:[+#]+|(?:[.-][a-z0-9]+)*)', s)) - STOP


JOB_DETAIL = re.compile(r'^\s*(?:[•*\-]\s*)?(job title|department|employment type|experience level)\s*[:：]\s*(.*?)\s*$', re.I)


def job_details(description):
    details = {}
    lines = [re.sub(r'^(?:#{1,6}\s+|[•*\-]\s+)', '', line.strip()).replace('**','').replace('__','').strip() for line in description.splitlines()]
    labels = {'job title':'job_title','position title':'job_title','role title':'job_title','department':'department','employment type':'employment_type','experience level':'experience_level'}
    for index, line in enumerate(lines):
        match = re.match(r'^(job title|position title|role title|department|employment type|experience level)\s*[:：]\s*(.*)$', line, re.I)
        if match:
            key, value = labels[match[1].lower()], match[2].strip()
            if not value:
                value = next((v for v in lines[index+1:] if v), '')
                if ':' in value or len(value)>200:
                    value = ''
            if value and key not in details:
                details[key] = value
    if 'job_title' not in details:
        for line in lines[:10]:
            match = re.match(r'^job description\s*[:：]\s*(.+)$', line, re.I)
            if match:
                details['job_title'] = match[1].strip()
                break
    return details


def is_job_section_heading(line):
    line = line.strip()
    if re.match(r'^#{1,6}\s+', line):
        return True
    # A fully bold numbered line is a section heading, not a numbered duty.
    return bool(re.fullmatch(r'(?:\*\*|__)\s*\d+[.)]\s+.+?(?:\*\*|__)\s*', line))


def extract_requirements(description):
    """Conservative source-preserving line/sentence extraction; always reviewable."""
    results = []
    priority = 'unspecified'
    for raw in description.splitlines():
        passage = raw.strip()
        if not passage:
            continue
        if is_job_section_heading(passage):
            heading_text=passage.lower()
            if re.search(r'preferred|nice.to.have|bonus',heading_text):
                priority='preferred'
            elif re.search(r'required|minimum|must.have',heading_text):
                priority='required'
            else:
                priority='unspecified'
            continue
        normalized=passage.replace('**','').replace('__','')
        clean = re.sub(r'^(?:[•*\-]\s*|\d+[.)]\s+)', '', normalized).strip()
        if job_details(clean) or JOB_DETAIL.match(clean):
            continue
        low = clean.lower()
        heading = len(clean) < 85 and (clean.endswith(':') or low in ('requirements', 'qualifications', 'required qualifications', 'preferred qualifications', 'nice to have', 'minimum qualifications'))
        if heading:
            if re.search(r'preferred|nice.to.have|bonus', low):
                priority = 'preferred'
            elif re.search(r'required|minimum|must.have', low):
                priority = 'required'
            else:
                priority = 'unspecified'
            continue
        if len(clean) < 3:
            continue
        # A heuristic candidate, never a claim of validated machine understanding.
        candidate = bool(re.search(r'experience|knowledge|proficien|familiar|ability|degree|certif|\byears?\b|\bmust\b|\brequired\b|\bpreferred\b|\bskills?\b', low))
        bullet = bool(re.match(r'^[•*\-]|^\d+[.)]', passage))
        if not (candidate or bullet or priority != 'unspecified'):
            continue
        for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])', clean):
            p = priority
            if re.search(r'preferred|nice.to.have|a plus|bonus', sentence, re.I):
                p = 'preferred'
            elif re.search(r'\bmust\b|\brequired\b|at least|minimum', sentence, re.I):
                p = 'required'
            kind = 'qualification' if re.search(r'degree|certif|\byears?\b', sentence, re.I) else 'skill/tool'
            results.append({'text': sentence, 'priority': p, 'kind': kind, 'source': passage})
    return results[:150]


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, label TEXT NOT NULL, name TEXT NOT NULL, location TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, linkedin TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS additional_sections (category TEXT PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS accomplishments (
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, preferred_version_id TEXT,
 FOREIGN KEY(preferred_version_id) REFERENCES versions(id) DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE IF NOT EXISTS versions (
 id TEXT PRIMARY KEY, accomplishment_id TEXT NOT NULL REFERENCES accomplishments(id),
 number INTEGER NOT NULL CHECK(number>0), parent_id TEXT REFERENCES versions(id),
 created_at TEXT NOT NULL, note TEXT NOT NULL, employer TEXT NOT NULL, role TEXT NOT NULL,
 project TEXT NOT NULL, bullet TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 tags TEXT NOT NULL, context TEXT NOT NULL, metrics TEXT NOT NULL, tailored_job_id TEXT REFERENCES jobs(id),
 UNIQUE(accomplishment_id, number));
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requirements (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), text TEXT NOT NULL,
 priority TEXT NOT NULL CHECK(priority IN ('required','preferred','unspecified')),
 kind TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS overrides (
 requirement_id TEXT NOT NULL REFERENCES requirements(id), version_id TEXT NOT NULL REFERENCES versions(id),
 label TEXT NOT NULL CHECK(label IN ('strong evidence','partial evidence','no evidence')),
 note TEXT NOT NULL, PRIMARY KEY(requirement_id, version_id));
CREATE TABLE IF NOT EXISTS applications (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS selections (
 application_id TEXT NOT NULL REFERENCES applications(id), position INTEGER NOT NULL CHECK(position>=0),
 version_id TEXT NOT NULL REFERENCES versions(id), PRIMARY KEY(application_id,position), UNIQUE(application_id,version_id));
CREATE TABLE IF NOT EXISTS resume_imports (
 id TEXT PRIMARY KEY, source_filename TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provenance (
 version_id TEXT PRIMARY KEY REFERENCES versions(id), import_id TEXT NOT NULL REFERENCES resume_imports(id),
 source_location TEXT NOT NULL, original_text TEXT NOT NULL, employment_dates TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_provenance_update BEFORE UPDATE ON provenance BEGIN
 SELECT RAISE(ABORT,'Import provenance is immutable.'); END;
CREATE TRIGGER IF NOT EXISTS immutable_provenance_delete BEFORE DELETE ON provenance BEGIN
 SELECT RAISE(ABORT,'Import provenance is immutable.'); END;
CREATE TRIGGER IF NOT EXISTS immutable_version_update BEFORE UPDATE ON versions BEGIN
 SELECT RAISE(ABORT,'Bullet versions are immutable; create a revision.'); END;
CREATE TRIGGER IF NOT EXISTS immutable_version_delete BEFORE DELETE ON versions BEGIN
 SELECT RAISE(ABORT,'Bullet versions are immutable.'); END;
"""
LEGACY_TABLES = ('jobs', 'accomplishments', 'versions', 'requirements', 'overrides', 'applications', 'selections')
TABLES = LEGACY_TABLES + ('resume_imports', 'provenance', 'profiles', 'additional_sections')
VERSION_FIELDS = ('employer', 'role', 'project', 'bullet', 'start_date', 'end_date', 'tags', 'context', 'metrics', 'tailored_job_id')
CATEGORIES = ('experience', 'education', 'project', 'skill', 'certification', 'interest')
DEFAULT_ADDITIONAL_SECTIONS = (('certification', 'Certifications'), ('interest', 'Interests'))
VERSION_FIELDS += ('category', 'title', 'date_text', 'location')


class Store:
    def __init__(self, path):
        self.path = str(path)
        self._previews = {}
        self._preview_lock = threading.RLock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            columns = {r['name'] for r in db.execute('PRAGMA table_info(versions)')}
            for name,default in (('category','experience'),('title',''),('date_text',''),('location','')):
                if name not in columns:
                    db.execute("ALTER TABLE versions ADD COLUMN " + name + " TEXT NOT NULL DEFAULT '" + default + "'")
            job_columns = {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}
            for name in ('department','employment_type','experience_level'):
                if name not in job_columns:
                    db.execute('ALTER TABLE jobs ADD COLUMN '+name+" TEXT NOT NULL DEFAULT ''")
                    for job_row in db.execute('SELECT id,description FROM jobs').fetchall():
                        value=job_details(job_row['description']).get(name,'')
                        db.execute('UPDATE jobs SET '+name+'=? WHERE id=?',(value,job_row['id']))
            db.execute('PRAGMA journal_mode=WAL')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def require(self, db, table, id):
        row = db.execute('SELECT * FROM ' + table + ' WHERE id=?', (id,)).fetchone()
        if row is None:
            raise ValidationError('The requested ' + table + ' record does not exist.')
        return dict(row)

    def version_payload(self, db, data):
        out = {}
        category = data.get('category','experience')
        if category not in CATEGORIES and (not isinstance(category,str) or not category.startswith('additional:') or not db.execute('SELECT 1 FROM additional_sections WHERE category=?',(category,)).fetchone()):
            raise ValidationError('Invalid entry category.')
        for k in VERSION_FIELDS:
            if k == 'category':
                out[k] = category
            elif k == 'tags':
                tags = data.get(k, [])
                if not isinstance(tags, list) or len(tags) > 100:
                    raise ValidationError('Skill tags must be a list of at most 100 items.')
                out[k] = json.dumps(sorted(set(text(t, 'Skill tag', True, 100) for t in tags)))
            elif k == 'tailored_job_id':
                out[k] = data.get(k) or None
                if out[k]:
                    self.require(db, 'jobs', out[k])
            else:
                required = k=='bullet' or (category=='experience' and k in ('employer','role')) or (category!='experience' and k=='title')
                out[k] = text(data.get(k, ''), k.replace('_', ' ').capitalize(), required)
        for k in ('start_date', 'end_date'):
            if out[k]:
                try:
                    dt.date.fromisoformat(out[k])
                except ValueError:
                    raise ValidationError('Dates must use YYYY-MM-DD.')
        if out['start_date'] and out['end_date'] and out['start_date'] > out['end_date']:
            raise ValidationError('End date must not be before start date.')
        return out

    def export_pdf(self, data):
        import io
        import sys
        from xml.sax.saxutils import escape
        sys.path.insert(0, str(ROOT/'vendor'/'pdf_export'))
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        ids = data.get('version_ids')
        if not isinstance(ids, list) or not ids or len(ids)>300 or any(not isinstance(i,str) for i in ids):
            raise ValidationError('Select between 1 and 300 entries to export.')
        contact = data.get('contact', {})
        if not isinstance(contact, dict):
            raise ValidationError('Invalid contact details.')
        contact = {key: text(contact.get(key,''), key.capitalize(), limit=300) for key in ('name','location','email','phone','linkedin')}
        title = text(contact['name'], 'Full name', required=True, limit=300)
        margins=data.get('margins',{})
        if not isinstance(margins,dict):
            raise ValidationError('Invalid margins.')
        checked={}
        for key,default in (('top',0.75),('bottom',0.75),('left',0.5),('right',0.5)):
            value=margins.get(key,default)
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not 0<=value<=5:
                raise ValidationError('Margins must be between 0 and 5 cm.')
            checked[key]=value*10*mm
        content_width=A4[0]-checked['left']-checked['right']
        font_choice=data.get('font','Arial')
        font_files={
            'Arial':('arial.ttf','arialbd.ttf','ariali.ttf','arialbi.ttf'),
            'Calibri':('calibri.ttf','calibrib.ttf','calibrii.ttf','calibriz.ttf'),
            'Times New Roman':('times.ttf','timesbd.ttf','timesi.ttf','timesbi.ttf'),
        }
        if font_choice not in font_files:
            raise ValidationError('Choose Arial, Calibri, or Times New Roman.')

        with self.connect() as db:
            entries = [self.require(db, 'versions', vid) for vid in ids]
            additional_names={category:name for category,name in DEFAULT_ADDITIONAL_SECTIONS}
            additional_names.update({row['category']:row['name'] for row in db.execute('SELECT category,name FROM additional_sections')})
        styles = getSampleStyleSheet()
        font_names=[font_choice.replace(' ','')+suffix for suffix in ('Regular','Bold','Italic','BoldItalic')]
        font_paths=[Path('C:/Windows/Fonts')/filename for filename in font_files[font_choice]]
        if not all(path.is_file() for path in font_paths):
            raise ValidationError(font_choice+' is not available on this computer.')
        for name,path in zip(font_names,font_paths):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name,str(path)))
        pdfmetrics.registerFontFamily(font_names[0],normal=font_names[0],bold=font_names[1],italic=font_names[2],boldItalic=font_names[3])
        for style in styles.byName.values():
            style.fontName=font_names[0]
        heading_font=font_names[1]
        position_font=font_names[3]
        for name in ('Title','Heading2','Heading3'):
            styles[name].fontName=heading_font
        for style in styles.byName.values():
            style.spaceBefore=0
            style.spaceAfter=0
        styles['BodyText'].leading=11
        styles['Title'].fontSize=16
        styles['Title'].leading=17
        styles['Heading2'].fontSize=12
        styles['Heading2'].leading=13
        styles['Heading3'].fontSize=10
        styles['Heading3'].leading=11
        styles['Heading2'].textColor=colors.black
        position_style=styles['Heading3'].clone('WorkPosition')
        position_style.fontName=position_font
        styles.add(position_style)
        right_style=styles['BodyText'].clone('WorkRight')
        right_style.alignment=2
        styles.add(right_style)
        def para(value, style='BodyText'):
            return Paragraph(escape(value).replace('\n','<br/>'), styles[style])
        def work_row(left,right,left_style):
            row=Table([[para(left,left_style) if left else '',para(right,'WorkRight') if right else '']],colWidths=[content_width*0.64,content_width*0.36],hAlign='LEFT')
            row.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),('VALIGN',(0,0),(-1,-1),'TOP')]))
            return row
        story=[]
        if contact['name']:story.append(para(contact['name'],'Title'))
        contact_line=' | '.join(contact[key] for key in ('location','email','phone','linkedin') if contact[key])
        if contact_line:
            styles.add(styles['BodyText'].clone('Contact'))
            styles['Contact'].alignment=1
            story.append(para(contact_line,'Contact'))
        story.append(Spacer(1,0.5*mm))
        labels={'experience':'Work experience','education':'Education','project':'Projects','skill':'Technical skills','additional':'Additional information'}
        sections={}
        for entry in entries:
            category=entry['category']
            major=category if category in ('experience','education','project','skill') else 'additional'
            groups=sections.setdefault(major,{}).setdefault(category,{})
            key=(entry['employer'].strip().casefold(),entry['role'].strip().casefold(),entry['title'].strip().casefold()) if category=='experience' else (entry['id'],)
            groups.setdefault(key,[]).append(entry)
        if 'education' in sections:
            education_entries=[entry for grouped in sections['education']['education'].values() for entry in grouped]
            def coursework(entry):
                title=entry['title'].strip()
                return bool(re.match(r'^(?:relevant\s+)?coursework\b',title,re.I) or
                            (not title and re.match(r'^(?:relevant\s+)?coursework\b',entry['bullet'].strip(),re.I)))
            degrees=[(index,entry) for index,entry in enumerate(education_entries) if not coursework(entry)]
            education_groups={}
            for index,entry in enumerate(education_entries):
                if coursework(entry):
                    school=entry['employer'].strip().casefold()
                    candidates=[(i,degree) for i,degree in degrees if not school or degree['employer'].strip().casefold()==school]
                    if candidates:
                        earlier=[candidate for candidate in candidates if candidate[0]<=index]
                        degree=(earlier[-1] if earlier else candidates[0])[1]
                        key=(degree['title'].strip().casefold(),degree['employer'].strip().casefold())
                    else:
                        key=('unmatched-coursework',entry['id'])
                else:
                    key=(entry['title'].strip().casefold(),entry['employer'].strip().casefold())
                education_groups.setdefault(key,[]).append(entry)
            for grouped in education_groups.values():
                grouped.sort(key=coursework)
            sections['education']['education']=education_groups
        def dates_for(entry):
            return entry['date_text'] or ' – '.join(entry[k] for k in ('start_date','end_date') if entry[k])
        def without_repeated_label(wording, label):
            wording=wording.strip()
            if not label:
                return wording
            if wording.casefold()==label.casefold():
                return ''
            prefix=re.match(r'^'+re.escape(label)+r'(?:\s*[:：]\s*|\s+[—–-]\s+|\s*\n\s*)',wording,re.I)
            return wording[prefix.end():].strip() if prefix else wording
        bullet_style=styles['BodyText'].clone('ResumeBullet')
        bullet_style.leftIndent=12
        bullet_style.firstLineIndent=-9
        styles.add(bullet_style)
        for major,categories in sections.items():
            story.append(para(labels[major], 'Heading2'))
            story.append(HRFlowable(width='100%', thickness=0.8, color=colors.black, spaceBefore=1, spaceAfter=2))
            for category,groups in categories.items():
                if major in ('additional','skill'):
                    section_name=additional_names[category] if major=='additional' else ''
                    singular=section_name[:-3]+'y' if section_name.lower().endswith('ies') else section_name[:-1] if section_name.lower().endswith('s') else section_name
                    items=[]
                    for grouped in groups.values():
                        for entry in grouped:
                            wording=entry['bullet'].strip()
                            item_title=entry['title'].strip()
                            if major=='additional':
                                wording=without_repeated_label(without_repeated_label(wording,section_name),singular)
                            if item_title and item_title.casefold() not in wording.casefold() and (major!='additional' or item_title.casefold() not in (section_name.casefold(),singular.casefold())):
                                wording=item_title+' — '+wording
                            wording=wording.strip(' ,;')
                            if not wording:
                                continue
                            date=dates_for(entry)
                            if date:wording+=' ('+date+')'
                            items.append(wording)
                    if major=='additional':
                        if items:
                            label='Interest' if category=='interest' and section_name=='Interests' else section_name
                            story.append(Paragraph(f'<b>{escape(label)}:</b> {escape(", ".join(items))}',styles['BodyText']))
                            story.append(Spacer(1,0.5*mm))
                    else:
                        for wording in items:
                            story.append(para(wording))
                            story.append(Spacer(1,0.5*mm))
                    continue
                for grouped in groups.values():
                    first=next((entry for entry in grouped if category!='education' or not coursework(entry)),grouped[0])
                    if category=='education':
                        if not coursework(first):
                            story.append(work_row(first['title'],first['location'],'Heading3'))
                            school=' · '.join(first[k] for k in ('employer','role') if first[k])
                            periods=list(dict.fromkeys(dates_for(entry) for entry in grouped if not coursework(entry) and dates_for(entry)))
                            if school or periods:story.append(work_row(school,'; '.join(periods),'BodyText'))
                    elif category=='experience':
                        locations=list(dict.fromkeys(entry['title'].strip() for entry in grouped if entry['title'].strip()))
                        story.append(work_row(first['employer'],'; '.join(locations),'Heading3'))
                    else:
                        heading=' · '.join(first[k] for k in ('title','employer','role') if first[k])
                        story.append(para(heading,'Heading3'))
                    dates=[dates_for(entry) for entry in grouped]
                    shared_date=dates[0] if len(set(dates))==1 else ''
                    if category=='experience':
                        periods=list(dict.fromkeys(date for date in dates if date))
                        story.append(work_row(first['role'],'; '.join(periods),'WorkPosition'))
                    elif category!='education' and shared_date:story.append(para(shared_date))
                    for entry,entry_date in zip(grouped,dates):
                        if category not in ('experience','education') and entry_date and not shared_date:story.append(para(entry_date))
                        if entry['project']:story.append(para(entry['project']))
                        if category=='education' and coursework(entry):
                            wording=entry['bullet'].strip()
                            if not re.match(r'^\s*(?:relevant\s+)?coursework\s*[:：]',wording,re.I):
                                wording='Relevant coursework: '+wording
                        else:
                            wording=without_repeated_label(entry['bullet'],entry['title']) if category in ('project','education') else entry['bullet'].strip()
                        if wording:
                            story.append(para('• '+wording,'ResumeBullet'))
                            story.append(Spacer(1,0.5*mm))
        output=io.BytesIO()
        doc=BaseDocTemplate(output,pagesize=A4,rightMargin=checked['right'],leftMargin=checked['left'],topMargin=checked['top'],bottomMargin=checked['bottom'],title=title)
        frame=Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
        doc.addPageTemplates(PageTemplate(id='resume',frames=[frame]))
        doc.build(story)
        return output.getvalue()

    def preview_pdf(self, data):
        import base64
        import io
        import pypdfium2
        pdf=pypdfium2.PdfDocument(self.export_pdf(data))
        pages=[]
        try:
            for index in range(len(pdf)):
                page=pdf[index]
                bitmap=page.render(scale=1.25)
                try:
                    image=bitmap.to_pil()
                    output=io.BytesIO()
                    image.save(output,format='PNG')
                    pages.append('data:image/png;base64,'+base64.b64encode(output.getvalue()).decode('ascii'))
                    image.close()
                finally:
                    bitmap.close()
                    page.close()
        finally:
            pdf.close()
        return {'pages':pages}

    def save_profile(self, data):
        values=[text(data.get(k,''),k.capitalize(),k in ('label','name'),300) for k in ('label','name','location','email','phone','linkedin')]
        with self.connect() as db:
            pid=data.get('id') or uid()
            if data.get('id'):
                self.require(db,'profiles',pid)
                db.execute('UPDATE profiles SET label=?,name=?,location=?,email=?,phone=?,linkedin=? WHERE id=?',(*values,pid))
            else:
                db.execute('INSERT INTO profiles VALUES (?,?,?,?,?,?,?)',(pid,*values))
        return {'id':pid}

    def save_additional_section(self, data):
        name=text(data.get('name',''), 'Section name', True, 80)
        if name.casefold() == 'additional information':
            raise ValidationError('Choose a subheading other than Additional Information.')
        with self.connect() as db:
            category=data.get('category')
            if category:
                existing=db.execute('SELECT position FROM additional_sections WHERE category=?',(category,)).fetchone()
                if category not in {key for key,_ in DEFAULT_ADDITIONAL_SECTIONS} and not existing:
                    raise ValidationError('The requested additional section does not exist.')
                position=existing['position'] if existing else next(i for i,(key,_) in enumerate(DEFAULT_ADDITIONAL_SECTIONS) if key==category)
            else:
                category='additional:'+uid()
                position=db.execute('SELECT COALESCE(MAX(position),2)+1 FROM additional_sections').fetchone()[0]
            db.execute('INSERT INTO additional_sections(category,name,position) VALUES (?,?,?) ON CONFLICT(category) DO UPDATE SET name=excluded.name',(category,name,position))
        return {'category':category,'name':name}

    def delete_entry(self, data):
        aid = text(data.get('id'), 'Entry ID', True)
        self.delete_entries({'ids':[aid]})
        return {'deleted': aid}

    def delete_entries(self, data):
        ids=data.get('ids')
        if not isinstance(ids,list) or not ids or len(ids)>1000:
            raise ValidationError('Select between 1 and 1000 entries.')
        ids=list(dict.fromkeys(text(i,'Entry ID',True) for i in ids))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for aid in ids:
                self._delete_entry(db,aid)
        return {'deleted':ids}

    def _delete_entry(self, db, aid):
        self.require(db, 'accomplishments', aid)
        if db.execute('SELECT 1 FROM selections s JOIN versions v ON v.id=s.version_id WHERE v.accomplishment_id=?', (aid,)).fetchone():
            raise ValidationError('This entry is used in a saved application. Remove it from that application and save the changes before deleting it.')
        # Allow deletion of a whole entry atomically; individual revisions remain immutable.
        db.execute('DROP TRIGGER immutable_provenance_delete')
        db.execute('DROP TRIGGER immutable_version_delete')
        db.execute('DELETE FROM overrides WHERE version_id IN (SELECT id FROM versions WHERE accomplishment_id=?)', (aid,))
        db.execute('DELETE FROM provenance WHERE version_id IN (SELECT id FROM versions WHERE accomplishment_id=?)', (aid,))
        db.execute('UPDATE accomplishments SET preferred_version_id=NULL WHERE id=?', (aid,))
        db.execute('DELETE FROM versions WHERE accomplishment_id=?', (aid,))
        db.execute('DELETE FROM accomplishments WHERE id=?', (aid,))
        db.execute("CREATE TRIGGER immutable_provenance_delete BEFORE DELETE ON provenance BEGIN SELECT RAISE(ABORT,'Import provenance is immutable.'); END")
        db.execute("CREATE TRIGGER immutable_version_delete BEFORE DELETE ON versions BEGIN SELECT RAISE(ABORT,'Bullet versions are immutable.'); END")

    def save_version(self, data):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return self._save_version(db, data)

    def _save_version(self, db, data):
        payload = self.version_payload(db, data)
        aid = data.get('accomplishment_id')
        if aid:
            self.require(db, 'accomplishments', aid)
            parent = self.require(db, 'versions', data.get('parent_id'))
            if parent['accomplishment_id'] != aid:
                raise ValidationError('Parent version belongs to a different accomplishment.')
            number = db.execute('SELECT MAX(number)+1 FROM versions WHERE accomplishment_id=?', (aid,)).fetchone()[0]
            parent_id = parent['id']
        else:
            aid, number, parent_id = uid(), 1, None
            db.execute('INSERT INTO accomplishments VALUES (?,?,NULL)', (aid, now()))
        vid = uid()
        values = [vid, aid, number, parent_id, now(), text(data.get('note', ''), 'Revision note')] + list(payload.values())
        db.execute('INSERT INTO versions VALUES (' + ','.join('?' for _ in values) + ')', values)
        if number == 1 or data.get('preferred', False):
            db.execute('UPDATE accomplishments SET preferred_version_id=? WHERE id=?', (vid, aid))
        return {'id': aid, 'version_id': vid, 'number': number}

    def restore(self, data):
        with self.connect() as db:
            source = self.require(db, 'versions', data.get('version_id'))
        source['tags'] = json.loads(source['tags'])
        source['parent_id'] = source['id']
        source['note'] = 'Restored from v' + str(source['number']) + (': ' + data['note'] if data.get('note') else '')
        source['preferred'] = data.get('preferred', True)
        return self.save_version(source)

    def preferred(self, data):
        with self.connect() as db:
            version = self.require(db, 'versions', data.get('version_id'))
            db.execute('UPDATE accomplishments SET preferred_version_id=? WHERE id=?', (version['id'], version['accomplishment_id']))
        return {'ok': True}

    def save_job(self, data):
        company = text(data.get('company', ''), 'Company', True)
        description = text(data.get('description', ''), 'Job description', True, 100000)
        title = text(job_details(description).get('job_title') or data.get('title', ''), 'Job title (not found in description; enter it manually)', True)
        jid = data.get('id') or uid()
        details=job_details(description)
        values=[text(data.get(k, '') if data.get('id') else (data.get(k) or details.get(k,'')),k.replace('_',' ').capitalize(),limit=300) for k in ('department','employment_type','experience_level')]
        extracted = extract_requirements(description)
        with self.connect() as db:
            if data.get('id'):
                self.require(db,'jobs',jid)
                db.execute('UPDATE jobs SET company=?,title=?,department=?,employment_type=?,experience_level=? WHERE id=?',(company,title,*values,jid))
                return {'id':jid,'count':0}
            db.execute('INSERT INTO jobs (id,company,title,description,created_at,department,employment_type,experience_level) VALUES (?,?,?,?,?,?,?,?)', (jid, company, title, description, now(), *values))
            for r in extracted:
                db.execute('INSERT INTO requirements VALUES (?,?,?,?,?,?)', (uid(), jid, r['text'], r['priority'], r['kind'], r['source']))
        return {'id': jid, 'count': len(extracted)}

    def save_requirement(self, data):
        with self.connect() as db:
            job = self.require(db, 'jobs', data.get('job_id'))
            source = text(data.get('source', ''), 'Source passage')
            if source and source not in job['description']:
                raise ValidationError('Source passage must be copied exactly from the saved description, or left empty for a manual requirement.')
            values = (text(data.get('text', ''), 'Requirement', True), choice(data.get('priority'), ('required','preferred','unspecified'), 'priority'), text(data.get('kind', 'skill/tool'), 'Kind', True, 100), source)
            rid = data.get('id')
            if rid:
                old = self.require(db, 'requirements', rid)
                if old['job_id'] != job['id']:
                    raise ValidationError('Requirement belongs to another job.')
                # Corrections are specific to requirement wording; stale overrides must not survive edits.
                db.execute('DELETE FROM overrides WHERE requirement_id=?', (rid,))
                db.execute('UPDATE requirements SET text=?,priority=?,kind=?,source=? WHERE id=?', values + (rid,))
            else:
                rid = uid()
                db.execute('INSERT INTO requirements VALUES (?,?,?,?,?,?)', (rid, job['id']) + values)
        return {'id': rid}

    def delete_requirement(self, data):
        with self.connect() as db:
            self.require(db, 'requirements', data.get('id'))
            db.execute('DELETE FROM overrides WHERE requirement_id=?', (data['id'],))
            db.execute('DELETE FROM requirements WHERE id=?', (data['id'],))
        return {'ok': True}

    def override(self, data):
        with self.connect() as db:
            self.require(db, 'requirements', data.get('requirement_id'))
            self.require(db, 'versions', data.get('version_id'))
            pair = (data['requirement_id'], data['version_id'])
            if data.get('label') == 'automatic':
                db.execute('DELETE FROM overrides WHERE requirement_id=? AND version_id=?', pair)
            else:
                label = choice(data.get('label'), LABELS, 'evidence label')
                note = text(data.get('note', ''), 'Correction explanation', True)
                db.execute('INSERT OR REPLACE INTO overrides VALUES (?,?,?,?)', pair + (label, note))
        return {'ok': True}

    def save_application(self, data):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.require(db, 'jobs', data.get('job_id'))
            name = text(data.get('name', ''), 'Application name', True)
            ids = data.get('version_ids', [])
            if not isinstance(ids, list) or not ids or len(ids) > 200 or len(ids) != len(set(ids)):
                raise ValidationError('Select between 1 and 200 distinct bullet versions.')
            versions = [self.require(db, 'versions', v) for v in ids]
            aids = [v['accomplishment_id'] for v in versions]
            if not data.get('allow_duplicates', False) and len(aids) != len(set(aids)):
                raise ValidationError('An application may contain only one version of each accomplishment unless duplicates are explicitly allowed.')
            appid = data.get('id')
            if appid:
                application = self.require(db, 'applications', appid)
                if application['job_id'] != data['job_id']:
                    raise ValidationError('An application cannot move to another job.')
                db.execute('UPDATE applications SET name=? WHERE id=?', (name, appid))
                db.execute('DELETE FROM selections WHERE application_id=?', (appid,))
            else:
                appid = uid()
                db.execute('INSERT INTO applications VALUES (?,?,?,?)', (appid, data['job_id'], name, now()))
            db.executemany('INSERT INTO selections VALUES (?,?,?)', [(appid, n, v) for n, v in enumerate(ids)])
        return {'id': appid}

    def state(self):
        with self.connect() as db:
            db.execute('BEGIN')
            result = {t: [dict(r) for r in db.execute('SELECT * FROM ' + t)] for t in TABLES}
        stored = {row['category'] for row in result['additional_sections']}
        result['additional_sections'].extend(
            {'category':category,'name':name,'position':position}
            for position,(category,name) in enumerate(DEFAULT_ADDITIONAL_SECTIONS)
            if category not in stored
        )
        result['additional_sections'].sort(key=lambda row:(row['position'],row['name']))
        for v in result['versions']:
            v['tags'] = json.loads(v['tags'])
        return result

    def backup(self):
        return {'format': 'resume-library', 'schema_version': 4, 'exported_at': now(), 'data': self.state()}

    def import_backup(self, backup):
        if not isinstance(backup, dict) or backup.get('format') != 'resume-library' or type(backup.get('schema_version')) is not int or backup['schema_version'] not in (1,2,3,4):
            raise ValidationError('Unsupported backup format. Expected resume-library schema version 1, 2, 3, or 4.')
        data = backup.get('data')
        if backup['schema_version'] == 1 and isinstance(data,dict) and set(data)==set(LEGACY_TABLES):
            data = dict(data, resume_imports=[], provenance=[])
        if isinstance(data,dict) and 'profiles' not in data:
            data=dict(data,profiles=[])
        if isinstance(data,dict) and 'additional_sections' not in data:
            data=dict(data,additional_sections=[])
        if not isinstance(data, dict) or set(data) != set(TABLES) or any(not isinstance(data[t], list) for t in TABLES):
            raise ValidationError('Backup is missing required data tables.')
        # Additive and atomic. Identical records are skipped; conflicts reject the whole import.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('PRAGMA defer_foreign_keys=ON')
            inserted = 0
            for table in TABLES:
                info = list(db.execute('PRAGMA table_info(' + table + ')'))
                columns = [r['name'] for r in info]
                keys = {'overrides': ['requirement_id','version_id'], 'selections': ['application_id','position'], 'provenance':['version_id'], 'additional_sections':['category']}.get(table, ['id'])
                for original in data[table]:
                    if table=='jobs' and isinstance(original,dict):
                        original=dict({'department':'','employment_type':'','experience_level':''},**original)
                    if table=='versions' and backup['schema_version']<3 and isinstance(original,dict):
                        original = dict({'category':'experience','title':'','date_text':''}, **original)
                    if table=='versions' and backup['schema_version']<4 and isinstance(original,dict):
                        original = dict({'location':''}, **original)
                    if not isinstance(original, dict) or set(original) != set(columns):
                        raise ValidationError('Invalid columns in backup table ' + table + '.')
                    row = dict(original)
                    for column in info:
                        if (column['notnull'] or column['pk']) and row[column['name']] is None:
                            raise ValidationError('Missing required backup field: ' + column['name'])
                    for k, value in row.items():
                        if (k == 'id' or k.endswith('_id')) and value is not None:
                            try:
                                if str(uuid.UUID(value)) != value:
                                    raise ValueError()
                            except (ValueError, TypeError, AttributeError):
                                raise ValidationError('Backup record IDs must be valid UUIDs.')
                        if k in ('number','position'):
                            if type(value) is not int:
                                raise ValidationError('Backup version numbers and positions must be integers.')
                        elif k == 'tags':
                            if not isinstance(value, list) or any(not isinstance(t, str) for t in value):
                                raise ValidationError('Invalid skill tags in backup.')
                            row[k] = json.dumps(value)
                        elif value is not None and not isinstance(value, str):
                            raise ValidationError('Invalid field type in backup: ' + k)
                    where = ' AND '.join(k + '=?' for k in keys)
                    old = db.execute('SELECT * FROM ' + table + ' WHERE ' + where, [row[k] for k in keys]).fetchone()
                    if old:
                        old = dict(old)
                        if table == 'versions':
                            old['tags'] = json.dumps(json.loads(old['tags']))
                        if old != row:
                            raise ValidationError('Backup conflicts with existing ' + table + ' data. Import into a new database to restore this snapshot; no data was changed.')
                        continue
                    db.execute('INSERT INTO ' + table + ' (' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')', [row[c] for c in columns])
                    inserted += 1
            if db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValidationError('Backup contains broken relationships.')
            for v in db.execute('SELECT * FROM versions').fetchall():
                payload = dict(v)
                payload['tags'] = json.loads(payload['tags'])
                self.version_payload(db, payload)
                if v['parent_id']:
                    parent = self.require(db, 'versions', v['parent_id'])
                    if parent['accomplishment_id'] != v['accomplishment_id'] or parent['number'] >= v['number']:
                        raise ValidationError('Invalid parent version relationship in backup.')
                elif v['number'] != 1:
                    raise ValidationError('Only the first version may have no parent.')
            for a in db.execute('SELECT * FROM accomplishments').fetchall():
                versions = db.execute('SELECT number FROM versions WHERE accomplishment_id=? ORDER BY number', (a['id'],)).fetchall()
                if [v['number'] for v in versions] != list(range(1, len(versions)+1)) or not versions:
                    raise ValidationError('Backup version sequence has gaps.')
                p = self.require(db, 'versions', a['preferred_version_id'])
                if p['accomplishment_id'] != a['id']:
                    raise ValidationError('Invalid preferred version relationship.')
            for r in db.execute('SELECT * FROM requirements').fetchall():
                if not r['text'].strip():
                    raise ValidationError('Backup contains an empty requirement.')
                j = self.require(db, 'jobs', r['job_id'])
                if r['source'] and r['source'] not in j['description']:
                    raise ValidationError('Backup requirement source is not in its job description.')
            for a in db.execute('SELECT * FROM applications').fetchall():
                positions = [r[0] for r in db.execute('SELECT position FROM selections WHERE application_id=? ORDER BY position', (a['id'],))]
                if not positions or positions != list(range(len(positions))):
                    raise ValidationError('Backup contains an invalid application selection order.')
        return {'inserted': inserted}

    def _preview(self, token):
        preview = self._previews.get(token)
        if not preview or time.monotonic() - preview['created'] > 1800:
            self._previews.pop(token, None)
            raise ValidationError('This preview expired or the server restarted. Upload or paste the resume again; nothing has been imported.')
        return preview['data']

    def preview_resume(self, data):
        try:
            preview = isolated_preview(data)
        except ResumeError as e:
            raise ValidationError(str(e))
        token = uid()
        with self._preview_lock:
            cutoff = time.monotonic()-1800
            self._previews = {k:v for k,v in self._previews.items() if v['created']>=cutoff}
            if len(self._previews)>=10:
                self._previews.pop(next(iter(self._previews)))
            self._previews[token] = {'created':time.monotonic(),'data':preview}
            result = dict(preview, token=token)
            result['duplicates'] = self.resume_duplicates({'token':token, 'items':preview['items']})['duplicates']
            return result

    def cancel_resume(self, data):
        with self._preview_lock:
            self._previews.pop(data.get('token'), None)
        return {'ok':True}

    def resume_duplicates(self, data):
        with self._preview_lock:
            preview = self._preview(data.get('token'))
            originals = {i['id'] for i in preview['items']}
            items = data.get('items')
            if not isinstance(items,list) or len(items)>300:
                raise ValidationError('Invalid preview items.')
            with self.connect() as db:
                versions = [dict(v) for v in db.execute('SELECT * FROM versions')]
            duplicates = {}
            for item in items:
                if not isinstance(item,dict) or item.get('id') not in originals:
                    raise ValidationError('Unknown preview bullet.')
                wording = text(item.get('bullet',''), 'Bullet text', True)
                candidates = duplicate_candidates(wording, versions)
                siblings = [{'id':i['id'],'accomplishment_id':i['id'],'number':1,'employer':'This resume','role':'Preview bullet','bullet':i['bullet']}
                            for i in items if i['id']!=item['id'] and i.get('selected',True) and i.get('action')!='skip']
                for c in duplicate_candidates(wording,siblings):
                    c['preview_item_id']=c.pop('version_id')
                    candidates.append(c)
                duplicates[item['id']] = candidates
            return {'duplicates':duplicates}

    def confirm_resume(self, data):
        token = text(data.get('token',''), 'Preview token', True, 100)
        with self._preview_lock:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                # Retrying a confirmed request cannot append a second set of versions.
                if db.execute('SELECT id FROM resume_imports WHERE id=?',(token,)).fetchone():
                    return {'imported':db.execute('SELECT COUNT(*) FROM provenance WHERE import_id=?',(token,)).fetchone()[0], 'already_imported':True}
                preview=self._preview(token)
                originals={i['id']:i for i in preview['items']}
                items=data.get('items')
                if not isinstance(items,list) or not items or len(items)>300:
                    raise ValidationError('Select at least one bullet, up to 300 per import.')
                seen=set(); prepared=[]
                for item in items:
                    if not isinstance(item,dict) or item.get('id') not in originals or item['id'] in seen:
                        raise ValidationError('Unknown or repeated preview bullet.')
                    seen.add(item['id'])
                    action=choice(item.get('action'), ('new','separate','revision','skip'), 'duplicate decision; choose skip, separate accomplishment, or revision')
                    if action=='skip':continue
                    original=originals[item['id']]
                    payload={k:item.get(k,'') for k in ('employer','role','project','bullet','start_date','end_date','title')}
                    payload['category']=item.get('category','experience')
                    payload['tags']=item.get('tags',[])
                    employment=text(item.get('employment_dates',''),'Employment dates',limit=500)
                    payload['date_text']=employment
                    payload['context']='Imported from resume. Employment dates as written: '+(employment or 'Not supplied')
                    payload['note']='Resume import: '+preview['source_filename']
                    payload['metrics']=''  # Claims remain in wording; extraction does not verify them.
                    if action=='revision':
                        parent=self.require(db,'versions',item.get('target_version_id'))
                        payload['accomplishment_id']=parent['accomplishment_id']
                        payload['parent_id']=parent['id']
                    self.version_payload(db,payload)
                    prepared.append((item,original,payload,employment))
                if not prepared:
                    raise ValidationError('No bullets selected for import.')
                stamp=now()
                db.execute('INSERT INTO resume_imports VALUES (?,?,?)',(token,preview['source_filename'],stamp))
                results=[]
                for item,original,payload,employment in prepared:
                    if item['action']=='new':
                        existing=[dict(v) for v in db.execute('SELECT * FROM versions')]
                        if duplicate_candidates(payload['bullet'],existing):
                            raise ValidationError('A possible duplicate exists. Recheck duplicates and explicitly choose skip, separate accomplishment, or revision. No bullets were imported.')
                    result=self._save_version(db,payload)
                    db.execute('INSERT INTO provenance VALUES (?,?,?,?,?)',(result['version_id'],token,original['source_location'],original['original_text'],employment))
                    results.append(result)
            # Drop preview contents only after the transaction commits successfully.
            self._previews.pop(token,None)
        return {'imported':len(results),'versions':results,'already_imported':False}

    def matches(self, jid, mode):
        choice(mode, ('keyword','semantic'), 'matching mode')
        state = self.state()
        if jid not in {j['id'] for j in state['jobs']}:
            raise ValidationError('Job does not exist.')
        reqs = [r for r in state['requirements'] if r['job_id'] == jid]
        corrections = {(o['requirement_id'], o['version_id']): o for o in state['overrides']}
        ranked = []
        for v in state['versions']:
            evidence = []
            for r in reqs:
                rt = tokens(r['text'], mode == 'semantic')
                # Employer, job title and unverified context are intentionally not evidence.
                body = tokens(v['bullet'] + ' ' + v['metrics'] + (' '+v['title'] if v['category']!='experience' else ''), mode == 'semantic')
                tag_tokens = tokens(' '.join(v['tags']), mode == 'semantic')
                if v['category']=='interest':
                    body,tag_tokens=set(),set()
                overlap = rt & body
                tag_overlap = (rt & tag_tokens) - overlap
                score = len(overlap) / max(1, len(rt))
                label = 'partial evidence' if overlap or tag_overlap else 'no evidence'
                # Text coverage cannot establish years, degrees, or numeric qualifications.
                complex_req = bool(re.search(r'\d|degree|certif|bachelor|master|doctor|phd', r['text'], re.I))
                if rt and score >= .8 and not complex_req and v['category']!='skill':
                    label = 'strong evidence'
                reasons = []
                if overlap:
                    reasons.append(('Shared concepts' if mode == 'semantic' else 'Shared terms') + ': ' + ', '.join(sorted(overlap)))
                if tag_overlap:
                    reasons.append('Tags only (not demonstrated in wording): ' + ', '.join(sorted(tag_overlap)))
                if not reasons:
                    reasons.append('No overlapping evidence found in this version or its tags')
                if v['category']=='skill' and (overlap or tag_overlap):
                    reasons.append('Self-reported skill entry; proficiency is not demonstrated by a skill listing alone')
                if v['category']=='interest':
                    reasons=['Interests are not used as automatic evidence of professional qualifications']
                if complex_req and overlap:
                    reasons.append('Numeric or credential qualification needs manual verification')
                correction = corrections.get((r['id'], v['id']))
                if correction:
                    label = correction['label']
                    reasons = ['Manual correction: ' + correction['note']]
                evidence.append({'requirement_id': r['id'], 'label': label, 'explanation': '. '.join(reasons) + '.', 'terms': sorted(overlap), 'manual': bool(correction), 'score': {'strong evidence':1, 'partial evidence':.4 + min(score,.5), 'no evidence':0}[label]})
            total_weight = sum(2 if r['priority'] == 'required' else 1 for r in reqs)
            score = sum(e['score'] * (2 if r['priority'] == 'required' else 1) for e,r in zip(evidence,reqs)) / max(total_weight,1)
            ranked.append({'version': v, 'score': round(score*100), 'evidence': evidence})
        preferred = {a['preferred_version_id'] for a in state['accomplishments']}
        ranked.sort(key=lambda m:(m['score'], m['version']['id'] in preferred, m['version']['number']), reverse=True)
        unsupported = [r for r in reqs if not any(any(e['requirement_id']==r['id'] and e['label']!='no evidence' for e in m['evidence']) for m in ranked)]
        partial = [r for r in reqs if r not in unsupported and not any(any(e['requirement_id']==r['id'] and e['label']=='strong evidence' for e in m['evidence']) for m in ranked)]
        return {'ranked': ranked, 'unsupported': unsupported, 'partial': partial, 'mode': mode}

    def diff(self, first, second):
        with self.connect() as db:
            a, b = self.require(db, 'versions', first), self.require(db, 'versions', second)
        if a['accomplishment_id'] != b['accomplishment_id']:
            raise ValidationError('Compare versions of the same accomplishment.')
        at, bt = re.findall(r'\s+|\S+', a['bullet']), re.findall(r'\s+|\S+', b['bullet'])
        changes = [{'op': tag, 'before': ''.join(at[i:j]), 'after': ''.join(bt[k:l])} for tag,i,j,k,l in difflib.SequenceMatcher(None,at,bt).get_opcodes()]
        metadata = {k: {'before': json.loads(a[k]) if k=='tags' else a[k], 'after': json.loads(b[k]) if k=='tags' else b[k]} for k in VERSION_FIELDS if k!='bullet' and a[k]!=b[k]}
        return {'changes': changes, 'metadata': metadata}

    def export_application(self, id, fmt):
        choice(fmt, ('txt','md'), 'export format')
        with self.connect() as db:
            a = self.require(db, 'applications', id)
            j = self.require(db, 'jobs', a['job_id'])
            vs = db.execute('SELECT v.* FROM selections s JOIN versions v ON v.id=s.version_id WHERE s.application_id=? ORDER BY s.position', (id,)).fetchall()
            additional_names={category:name for category,name in DEFAULT_ADDITIONAL_SECTIONS}
            additional_names.update({row['category']:row['name'] for row in db.execute('SELECT category,name FROM additional_sections')})
        heading = a['name'] + '\n' + j['company'] + ' — ' + j['title']
        if fmt == 'md':
            heading = '# ' + a['name'] + '\n\n' + j['company'] + ' — ' + j['title']
        lines=[];previous=None
        labels={'experience':'Work experience','education':'Education','project':'Projects','skill':'Technical skills',**additional_names}
        sectional=any(v['category']!='experience' for v in vs)
        for v in vs:
            if sectional and v['category']!=previous:
                lines.extend(['',('## ' if fmt=='md' else '')+labels[v['category']]])
                previous=v['category']
            wording=v['bullet']
            if v['category']!='experience':
                description=' · '.join(x for x in (v['title'],v['employer'],v['date_text']) if x and x.casefold() not in wording.casefold())
                if description:wording=description+' — '+wording
            lines.append('- '+wording.replace('\n','\n  '))
        return heading + '\n\n' + '\n'.join(lines).lstrip('\n') + '\n'


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, status=200, content_type='application/json; charset=utf-8', filename=None):
            raw = json.dumps(value).encode() if content_type.startswith('application/json') else (value.encode() if isinstance(value,str) else value)
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if filename:
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(filename,safe=''))
            self.end_headers()
            self.wfile.write(raw)

        def safe_host(self):
            host = self.headers.get('Host', '')
            expected = {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)}
            return host in expected

        def do_GET(self):
            if not self.safe_host():
                return self.reply({'error':'Invalid local host.'}, 403)
            u = urlparse(self.path)
            q = parse_qs(u.query)
            try:
                if u.path == '/api/state':
                    return self.reply(store.state())
                if u.path == '/api/backup':
                    return self.reply(store.backup(), filename='resume-library-backup.json')
                if u.path == '/api/matches':
                    return self.reply(store.matches(q.get('job_id',[''])[0], q.get('mode',['keyword'])[0]))
                if u.path == '/api/diff':
                    return self.reply(store.diff(q.get('a',[''])[0], q.get('b',[''])[0]))
                if u.path == '/api/export':
                    fmt = q.get('format',['txt'])[0]
                    output = store.export_application(q.get('id',[''])[0],fmt)
                    return self.reply(output, content_type='text/plain; charset=utf-8', filename='application.'+fmt)
                files = {'/logo.png': ('logo.png','image/png'), '/': ('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript; charset=utf-8'), '/resume.js':('resume.js','text/javascript; charset=utf-8'), '/resume.css':('resume.css','text/css; charset=utf-8'), '/style.css':('style.css','text/css; charset=utf-8')}
                if u.path in files:
                    file,mime = files[u.path]
                    return self.reply((ROOT/'static'/file).read_bytes(),content_type=mime)
                return self.reply({'error':'Not found.'},404)
            except ValidationError as e:
                return self.reply({'error':str(e)},400)

        def do_POST(self):
            if not self.safe_host() or self.headers.get('Origin') not in (None, 'http://' + self.headers.get('Host','')) or self.headers.get('X-Resume-App') != '1':
                return self.reply({'error':'This request must come from the local app.'},403)
            try:
                size = int(self.headers.get('Content-Length','0'))
                if size < 1 or size > 20_000_000:
                    raise ValidationError('Request must contain JSON under 20 MB.')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data,dict):
                    raise ValidationError('Expected a JSON object.')
                if urlparse(self.path).path == '/api/export/pdf':
                    filename=text(data.get('application_name','Application'), 'Application name', limit=300) or 'Application'
                    filename=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename).rstrip('. ') or 'Application'
                    pdf=store.export_pdf(data)
                    return self.reply(pdf, content_type='application/pdf', filename=filename+'.pdf')
                routes = {'/api/export/preview':store.preview_pdf, '/api/profile':store.save_profile, '/api/additional-section':store.save_additional_section, '/api/entries/delete':store.delete_entries, '/api/entry/delete':store.delete_entry, '/api/version':store.save_version, '/api/restore':store.restore, '/api/preferred':store.preferred, '/api/job':store.save_job, '/api/requirement':store.save_requirement, '/api/requirement/delete':store.delete_requirement, '/api/override':store.override, '/api/application':store.save_application, '/api/import':store.import_backup}
                routes.update({'/api/resume/preview':store.preview_resume, '/api/resume/cancel':store.cancel_resume, '/api/resume/duplicates':store.resume_duplicates, '/api/resume/confirm':store.confirm_resume})
                action = routes.get(urlparse(self.path).path)
                if not action:
                    return self.reply({'error':'Not found.'},404)
                return self.reply(action(data))
            except (ValidationError, ValueError, TypeError, KeyError, sqlite3.IntegrityError) as e:
                return self.reply({'error':str(e) if isinstance(e,ValidationError) else 'Invalid data or broken relationship. No changes were saved.'},400)
            except sqlite3.OperationalError:
                return self.reply({'error':'Database is unavailable or busy. Please retry.'},503)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(ROOT/'data'/'resume.sqlite3'))
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(Store(args.db)))
    print('Resume.Home running at http://127.0.0.1:' + str(args.port), flush=True)
    print('Database: ' + str(Path(args.db).resolve()), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
