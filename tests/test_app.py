import copy
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Store, ValidationError, extract_requirements, make_handler


class Workflows(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'resume.sqlite3'
        self.s = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def bullet(self, **kw):
        data = dict(employer='Acme', role='Analyst', bullet='Automated Python reporting, saving 8 hours weekly.', tags=['Python','Automation'], metrics='8 hours weekly; time logs', context='Monthly report workflow', note='Initial')
        data.update(kw)
        return self.s.save_version(data)

    def job(self):
        return self.s.save_job(dict(company='Example',title='Data Analyst',description='Required qualifications:\n- Python\n- SQL\n- At least 5 years of experience\nPreferred qualifications:\n- Leadership\n- Kubernetes'))['id']

    def test_three_revisions_restore_and_immutability(self):
        a = self.bullet()
        b = self.bullet(accomplishment_id=a['id'],parent_id=a['version_id'],bullet='Built Python reporting, saving 8 hours weekly.',note='Clearer verb')
        c = self.bullet(accomplishment_id=a['id'],parent_id=b['version_id'],bullet='Automated weekly Python reports to save 8 hours.',note='Shortened')
        self.assertEqual([v['number'] for v in self.s.state()['versions']], [1,2,3])
        diff = self.s.diff(a['version_id'], c['version_id'])
        self.assertTrue(any(x['op']!='equal' for x in diff['changes']))
        restored = self.s.restore({'version_id':a['version_id']})
        vs = self.s.state()['versions']
        self.assertEqual(restored['number'],4)
        self.assertEqual(vs[3]['bullet'],vs[0]['bullet'])
        self.assertEqual(vs[3]['parent_id'],vs[0]['id'])
        self.assertEqual(self.s.state()['accomplishments'][0]['preferred_version_id'],restored['version_id'])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.s.connect() as db:
                db.execute('UPDATE versions SET bullet=? WHERE id=?',('changed',a['version_id']))
        with self.assertRaises(sqlite3.IntegrityError):
            with self.s.connect() as db:
                db.execute('DELETE FROM versions WHERE id=?',(a['version_id'],))

    def test_branch_tailoring_and_cross_parent_rejected(self):
        a=self.bullet(); b=self.bullet(); j=self.job()
        with self.assertRaises(ValidationError):
            self.bullet(accomplishment_id=a['id'],parent_id=b['version_id'])
        v=self.bullet(accomplishment_id=a['id'],parent_id=a['version_id'],tailored_job_id=j,tags=['Python','SQL'])
        state=self.s.state()
        self.assertEqual(state['versions'][-1]['tailored_job_id'],j)
        self.assertNotIn('SQL',state['versions'][0]['tags'])
        self.assertEqual(state['accomplishments'][0]['preferred_version_id'],a['version_id'])

    def test_extraction_priorities_source_and_manual_edit(self):
        j=self.job(); state=self.s.state(); reqs=state['requirements']
        self.assertEqual(len(reqs),5)
        self.assertEqual([r['priority'] for r in reqs],['required']*3+['preferred']*2)
        self.assertTrue(all(r['source'] in state['jobs'][0]['description'] for r in reqs))
        r=reqs[0]
        self.s.save_requirement(dict(r,text='Python programming',priority='preferred'))
        self.assertEqual(self.s.state()['requirements'][0]['text'],'Python programming')
        with self.assertRaises(ValidationError):
            self.s.save_requirement(dict(r,source='Invented passage'))
        manual=self.s.save_requirement(dict(job_id=j,text='Communication',priority='unspecified',kind='skill/tool',source=''))
        self.s.delete_requirement(manual)
        self.assertEqual(len(self.s.state()['requirements']),5)
        self.assertEqual(extract_requirements('Experience with Python')[0]['priority'],'unspecified')
        self.assertEqual(extract_requirements('Required:\n- 5 years Python experience')[0]['text'],'5 years Python experience')

    def test_matching_keywords_semantics_gaps_and_overrides(self):
        a=self.bullet(bullet='Led reporting and automated Python workflows.',tags=['SQL'],metrics='')
        j=self.job()
        kw=self.s.matches(j,'keyword');sem=self.s.matches(j,'semantic')
        requirements={r['text']:r['id'] for r in self.s.state()['requirements']}
        labels=lambda m:{e['requirement_id']:e['label'] for e in m['ranked'][0]['evidence']}
        self.assertEqual(labels(kw)[requirements['Python']],'strong evidence')
        self.assertEqual(labels(kw)[requirements['SQL']],'partial evidence')
        self.assertEqual(labels(kw)[requirements['Leadership']],'no evidence')
        self.assertEqual(labels(sem)[requirements['Leadership']],'strong evidence')
        self.assertIn('Kubernetes',[r['text'] for r in sem['unsupported']])
        self.assertIn('SQL',[r['text'] for r in sem['partial']])
        data=dict(requirement_id=requirements['Python'],version_id=a['version_id'],label='no evidence',note='This is a training example, not work evidence.')
        self.s.override(data)
        self.assertEqual(labels(self.s.matches(j,'semantic'))[requirements['Python']],'no evidence')
        self.s.override(dict(data,label='automatic'))
        self.assertEqual(labels(self.s.matches(j,'keyword'))[requirements['Python']],'strong evidence')

    def test_requirement_edit_clears_stale_corrections(self):
        a=self.bullet();j=self.job();r=self.s.state()['requirements'][0]
        self.s.override(dict(requirement_id=r['id'],version_id=a['version_id'],label='no evidence',note='Reviewed'))
        self.s.save_requirement(dict(r,text='Python automation'))
        self.assertEqual(self.s.state()['overrides'],[])

    def test_credential_requires_manual_verification(self):
        self.bullet(bullet='5 years Python experience and bachelor degree',tags=[],metrics='')
        j=self.s.save_job(dict(company='X',title='Y',description='Required:\n- 5 years Python experience\n- Bachelor degree'))['id']
        m=self.s.matches(j,'semantic')
        self.assertTrue(all(e['label']=='partial evidence' for e in m['ranked'][0]['evidence']))

    def test_application_exact_versions_order_exports_restart(self):
        a=self.bullet(); b=self.bullet(bullet='Built SQL dashboards.')
        j=self.job(); ids=[b['version_id'],a['version_id']]
        app=self.s.save_application(dict(job_id=j,name='Analyst application',version_ids=ids))['id']
        before=self.s.export_application(app,'txt')
        self.bullet(accomplishment_id=a['id'],parent_id=a['version_id'],bullet='New wording',preferred=True)
        restarted=Store(self.path)
        self.assertEqual(restarted.export_application(app,'txt'),before)
        self.assertTrue(before.index('Built SQL')<before.index('Automated Python'))
        self.assertTrue(restarted.export_application(app,'md').startswith('# Analyst application'))
        self.s.save_application(dict(id=app,job_id=j,name='Reordered',version_ids=ids[::-1]))
        self.assertTrue(self.s.export_application(app,'txt').index('Automated')<self.s.export_application(app,'txt').index('Built SQL'))

    def test_duplicate_accomplishments_blocked_by_default(self):
        a=self.bullet(); b=self.bullet(accomplishment_id=a['id'],parent_id=a['version_id']); j=self.job()
        data=dict(job_id=j,name='Application',version_ids=[a['version_id'],b['version_id']])
        with self.assertRaises(ValidationError):self.s.save_application(data)
        self.s.save_application(dict(data,allow_duplicates=True))
        self.assertEqual(len(self.s.state()['selections']),2)

    def test_full_backup_roundtrip_preserves_all_relationships(self):
        a=self.bullet();j=self.job();b=self.bullet(accomplishment_id=a['id'],parent_id=a['version_id'],tailored_job_id=j)
        self.s.restore(dict(version_id=a['version_id']))
        self.s.save_application(dict(job_id=j,name='Snapshot',version_ids=[b['version_id']]))
        self.s.override(dict(requirement_id=self.s.state()['requirements'][0]['id'],version_id=b['version_id'],label='strong evidence',note='Verified by owner'))
        backup=json.loads(json.dumps(self.s.backup()))
        other=Store(Path(self.temp.name)/'restored.sqlite3')
        self.assertGreater(other.import_backup(backup)['inserted'],0)
        self.assertEqual(other.state(),self.s.state())
        self.assertEqual(other.import_backup(backup)['inserted'],0)

    def test_import_bad_parent_and_conflict_are_atomic(self):
        a=self.bullet();self.bullet(accomplishment_id=a['id'],parent_id=a['version_id'])
        backup=self.s.backup(); broken=copy.deepcopy(backup);broken['data']['versions'][1]['parent_id']='missing'
        other=Store(Path(self.temp.name)/'other.sqlite3')
        with self.assertRaises(ValidationError):other.import_backup(broken)
        self.assertEqual(other.state()['versions'],[])
        other.import_backup(backup)
        changed=copy.deepcopy(backup);changed['data']['versions'][0]['bullet']='Changed immutable record'
        with self.assertRaises(ValidationError):other.import_backup(changed)
        self.assertEqual(other.state(),self.s.state())
        broken=copy.deepcopy(backup);broken['data']['versions'][0]['parent_id']=broken['data']['versions'][1]['id']
        empty=Store(Path(self.temp.name)/'empty.sqlite3')
        with self.assertRaises(ValidationError):empty.import_backup(broken)
        self.assertEqual(empty.state()['versions'],[])

    def test_delete_entry_and_all_revisions(self):
        a=self.bullet()
        self.bullet(accomplishment_id=a['id'],parent_id=a['version_id'])
        other=self.bullet()
        self.s.delete_entry({'id':a['id']})
        state=self.s.state()
        self.assertEqual([v['id'] for v in state['versions']],[other['version_id']])
        with self.s.connect() as db:
            self.assertEqual(list(db.execute('PRAGMA foreign_key_check')),[])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM versions WHERE id=?',(other['version_id'],))
        with self.assertRaises(ValidationError):self.s.delete_entry({'id':a['id']})

    def test_delete_preserves_saved_applications(self):
        a=self.bullet(); j=self.job()
        self.s.save_application(dict(job_id=j,name='Saved',version_ids=[a['version_id']]))
        before=self.s.state()
        with self.assertRaises(ValidationError):self.s.delete_entry({'id':a['id']})
        self.assertEqual(self.s.state(),before)

    def test_direct_pdf_export(self):
        a=self.bullet()
        pdf=self.s.export_pdf({'contact':{'name':'Alex Example','location':'Singapore','email':'alex@example.com','phone':'+65 1234 5678','linkedin':'linkedin.com/in/alex'},'version_ids':[a['version_id']]})
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertIn(b'%%EOF',pdf)
        with self.assertRaises(ValidationError):self.s.export_pdf({'version_ids':[]})
        with self.assertRaises(ValidationError):self.s.export_pdf({'version_ids':['missing']})

    def test_job_title_extracted_from_original_description(self):
        for title in ('Senior Software Engineer (Platform)', 'Mergers & Acquisitions (M&A) Analyst', 'Customer Success Lead'):
            result=self.s.save_job({'company':'Example','title':'Short label','description':'# Job Description: Other heading\n**Job Title:** '+title+'\n**Department:** Operations\n- Python experience required'})
            with self.s.connect() as db:
                record=self.s.require(db,'jobs',result['id'])
            self.assertEqual(record['title'],title)
            self.assertEqual(record['department'],'Operations')
        result=self.s.save_job({'company':'Example','description':'Job Description: Research Associate\n- Research experience required'})
        with self.s.connect() as db:self.assertEqual(self.s.require(db,'jobs',result['id'])['title'],'Research Associate')
        with self.assertRaises(ValidationError):self.s.save_job({'company':'Example','description':'We need analytical skills.'})

    def test_markdown_job_headings_are_not_requirements(self):
        source='### Key Responsibilities\n**1. Financial Analysis & Valuation**\n- Build **financial models**.\n__2. Market Research__\n1. Conduct market research.\n### Preferred qualifications\n- Python experience'
        rows=extract_requirements(source)
        self.assertEqual([r['text'] for r in rows],['Build financial models.','Conduct market research.','Python experience'])
        self.assertEqual(rows[-1]['priority'],'preferred')
        self.assertEqual(rows[0]['source'],'- Build **financial models**.')

    def test_bulk_delete_is_atomic(self):
        a=self.bullet();b=self.bullet();j=self.job()
        self.s.save_application(dict(job_id=j,name='Protected',version_ids=[b['version_id']]))
        before=self.s.state()
        with self.assertRaises(ValidationError):self.s.delete_entries({'ids':[a['id'],b['id']]})
        self.assertEqual(before,self.s.state())
        c=self.bullet()
        self.s.delete_entries({'ids':[a['id'],c['id']]})
        self.assertEqual([v['id'] for v in self.s.state()['accomplishments']],[b['id']])

    def test_contact_profiles_persist_and_backup(self):
        data=dict(label='Personal',name='Alex',location='Singapore',email='alex@example.com',phone='123',linkedin='linkedin.com/in/alex')
        result=self.s.save_profile(data)
        self.assertEqual(Store(self.path).state()['profiles'][0]['name'],'Alex')
        self.s.save_profile(dict(data,id=result['id'],phone='456'))
        other=Store(Path(self.temp.name)/'profile-copy.sqlite3')
        other.import_backup(self.s.backup())
        self.assertEqual(other.state()['profiles'][0]['phone'],'456')
        legacy=self.s.backup();legacy['data'].pop('profiles')
        Store(Path(self.temp.name)/'old-copy.sqlite3').import_backup(legacy)

    def test_pdf_preview_pages(self):
        a=self.bullet()
        result=self.s.preview_pdf({'contact':{'name':'Alex'},'version_ids':[a['version_id']]})
        self.assertEqual(len(result['pages']),1)
        self.assertTrue(result['pages'][0].startswith('data:image/png;base64,iVBOR'))

    def test_pdf_groups_points_for_same_employer_and_role(self):
        import pypdfium2
        first=self.bullet(employer='Goldman Sachs',role='Financial Analyst',bullet='Built a valuation model.')
        other=self.bullet(employer='Other Company',role='Analyst',bullet='Analyzed market data.')
        second=self.bullet(employer='goldman sachs',role='financial analyst',bullet='Prepared transaction materials.')
        ids=[item['version_id'] for item in (first,other,second)]
        pdf=pypdfium2.PdfDocument(self.s.export_pdf({'contact':{'name':'Alex'},'version_ids':ids}))
        try:
            content=' '.join(page.get_textpage().get_text_range() for page in pdf)
        finally:
            pdf.close()
        self.assertEqual(content.count('Goldman Sachs'),1)
        self.assertEqual(content.count('Financial Analyst'),1)
        self.assertRegex(content,r'Goldman Sachs\s+Financial Analyst')
        self.assertNotIn('Goldman Sachs · Financial Analyst',content)
        self.assertIn('Built a valuation model.',content)
        self.assertIn('Prepared transaction materials.',content)
        self.assertLess(content.index('Built a valuation model.'),content.index('Prepared transaction materials.'))

    def test_pdf_work_heading_places_location_and_dates_with_their_labels(self):
        import pypdfium2
        entry=self.bullet(employer='Goldman Sachs',role='Financial Analyst',title='Vancouver, Canada',date_text='July 2023 - Present')
        pdf=pypdfium2.PdfDocument(self.s.export_pdf({'contact':{'name':'Alex'},'version_ids':[entry['version_id']]}))
        try:
            content=' '.join(page.get_textpage().get_text_range() for page in pdf)
        finally:
            pdf.close()
        self.assertRegex(content,r'Goldman Sachs\s+Vancouver, Canada\s+Financial Analyst\s+July 2023 - Present')
        self.assertEqual(content.count('July 2023 - Present'),1)

    def test_pdf_compact_sections_do_not_repeat_titles(self):
        import pypdfium2
        entries=[
            self.bullet(category='interest',title='Photography',employer='',role='',bullet='Photography'),
            self.bullet(category='interest',title='Hiking',employer='',role='',bullet='Hiking'),
            self.bullet(category='certification',title='CFA Level I',employer='',role='',bullet='CFA Level I'),
            self.bullet(category='skill',title='Python',employer='',role='',bullet='Python automation'),
        ]
        pdf=pypdfium2.PdfDocument(self.s.export_pdf({'contact':{'name':'Alex'},'version_ids':[entry['version_id'] for entry in entries]}))
        try:
            content=' '.join(page.get_textpage().get_text_range() for page in pdf)
        finally:
            pdf.close()
        self.assertEqual(content.count('Additional information'),1)
        self.assertEqual(content.count('Interest: Photography, Hiking'),1)
        self.assertEqual(content.count('Certifications: CFA Level I'),1)
        self.assertEqual(content.count('Technical skills'),1)
        self.assertIn('Photography',content)
        self.assertIn('Hiking',content)
        self.assertIn('Python automation',content)
        self.assertNotIn('Skill:',content)
        self.assertEqual(content.count('CFA Level I'),1)

    def test_pdf_removes_repeated_project_and_interest_labels(self):
        import pypdfium2
        project=self.bullet(category='project',title='Portfolio Optimization Analysis',employer='',role='',bullet='Portfolio Optimization Analysis: Modeled asset allocations.')
        interest=self.bullet(category='interest',title='Interest',employer='',role='',bullet='Interest: Photography')
        another=self.bullet(category='interest',title='Gardening',employer='',role='',bullet='Gardening')
        ids=[item['version_id'] for item in (project,interest,another)]
        pdf=pypdfium2.PdfDocument(self.s.export_pdf({'contact':{'name':'Alex'},'version_ids':ids}))
        try:
            content=' '.join(page.get_textpage().get_text_range() for page in pdf)
        finally:
            pdf.close()
        self.assertEqual(content.count('Portfolio Optimization Analysis'),1)
        self.assertIn('Modeled asset allocations.',content)
        self.assertEqual(content.count('Interest: Photography, Gardening'),1)
        self.assertIn('Photography',content)
        self.assertIn('Gardening',content)

    def test_pdf_coursework_is_bullet_under_degree(self):
        import pypdfium2
        degree=self.bullet(category='education',title='Bachelor of Science in Finance',employer='Example University',role='',bullet='Studied corporate finance.')
        coursework=self.bullet(category='education',title='Relevant Coursework: Portfolio Theory, Accounting',employer='',role='',bullet='Relevant Coursework: Portfolio Theory, Accounting')
        other=self.bullet(category='education',title='Master of Finance',employer='Another University',role='',bullet='Researched capital markets.')
        ids=[item['version_id'] for item in (degree,coursework,other)]
        pdf=pypdfium2.PdfDocument(self.s.export_pdf({'contact':{'name':'Alex'},'version_ids':ids}))
        try:
            content=' '.join(page.get_textpage().get_text_range() for page in pdf)
        finally:
            pdf.close()
        self.assertEqual(content.count('Bachelor of Science in Finance'),1)
        self.assertIn('Relevant Coursework: Portfolio Theory, Accounting',content)
        self.assertEqual(content.count('Relevant Coursework: Portfolio Theory, Accounting'),1)
        self.assertLess(content.index('Bachelor of Science in Finance'),content.index('Relevant Coursework: Portfolio Theory, Accounting'))
        self.assertEqual(content.count('Master of Finance'),1)

    def test_pdf_education_pairs_degree_with_location_and_school_with_dates(self):
        import pypdfium2
        degree=self.bullet(category='education',title='Bachelor of Science',employer='Example University',role='Finance',location='Vancouver, Canada',date_text='2020–2024',bullet='Studied finance.')
        pdf=pypdfium2.PdfDocument(self.s.export_pdf({'contact':{'name':'Alex'},'version_ids':[degree['version_id']]}))
        try:
            content=' '.join(page.get_textpage().get_text_range() for page in pdf)
        finally:
            pdf.close()
        for value in ('Bachelor of Science','Vancouver, Canada','Example University · Finance','2020–2024'):
            self.assertEqual(content.count(value),1)
        self.assertLess(content.index('Bachelor of Science'),content.index('Example University'))

    def test_additional_information_sections_are_editable_and_exported(self):
        import pypdfium2
        language=self.s.save_additional_section({'name':'Languages'})
        item=self.bullet(category=language['category'],title='Spanish',employer='',role='',bullet='Spanish — fluent')
        interest=self.bullet(category='interest',title='Photography',employer='',role='',bullet='Photography')
        self.s.save_additional_section({'category':'interest','name':'Hobbies'})
        ids=[item['version_id'],interest['version_id']]
        pdf=pypdfium2.PdfDocument(self.s.export_pdf({'contact':{'name':'Alex'},'version_ids':ids}))
        try:
            content=' '.join(page.get_textpage().get_text_range() for page in pdf)
        finally:
            pdf.close()
        self.assertEqual(content.count('Additional information'),1)
        self.assertEqual(content.count('Languages: Spanish — fluent'),1)
        self.assertEqual(content.count('Hobbies: Photography'),1)
        self.assertNotIn('Language:',content)
        self.assertNotIn('Hobby:',content)
        self.assertNotIn('Interests',content)
        other=Store(Path(self.temp.name)/'additional-copy.sqlite3')
        other.import_backup(self.s.backup())
        self.assertEqual(other.state()['additional_sections'],self.s.state()['additional_sections'])
        self.assertEqual(other.state()['versions'],self.s.state()['versions'])

    def test_pdf_custom_margins(self):
        a=self.bullet()
        data={'contact':{'name':'Alex'},'version_ids':[a['version_id']],'margins':{'top':1.5,'bottom':1,'left':2,'right':2}}
        self.assertTrue(self.s.export_pdf(data).startswith(b'%PDF-'))
        for value in (-1,6,float('nan'),'1',True):
            with self.assertRaises(ValidationError):self.s.export_pdf(dict(data,margins={'top':value}))

    def test_pdf_preview_supports_common_word_fonts(self):
        a=self.bullet(employer='Example',role='Analyst',bullet='Prepared reports.')
        data={'contact':{'name':'Alex'},'version_ids':[a['version_id']]}
        for font in ('Arial','Calibri','Times New Roman'):
            pdf=self.s.export_pdf(dict(data,font=font))
            self.assertTrue(pdf.startswith(b'%PDF-'))
            self.assertIn(font.replace(' ','').encode(),pdf)
            self.assertTrue(self.s.preview_pdf(dict(data,font=font))['pages'])
        with self.assertRaises(ValidationError):
            self.s.export_pdf(dict(data,font='Comic Sans'))

    def test_input_validation(self):
        for changes in [dict(bullet=' '),dict(employer=''),dict(tags='Python'),dict(start_date='2025-02-30'),dict(start_date='2025-03-01',end_date='2024-01-01')]:
            with self.assertRaises(ValidationError):self.bullet(**changes)
        self.assertEqual(self.s.state()['accomplishments'],[])

    def test_concurrent_revision_numbers(self):
        a=self.bullet();results=[];errors=[]
        def save():
            try: results.append(self.bullet(accomplishment_id=a['id'],parent_id=a['version_id']))
            except Exception as e:errors.append(e)
        ts=[threading.Thread(target=save) for _ in range(4)]
        for t in ts:t.start()
        for t in ts:t.join()
        self.assertEqual(errors,[])
        self.assertEqual(sorted(r['number'] for r in results),[2,3,4,5])

    def test_http_workflow_and_origin_guard(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.s));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(base+'/') as res:
                page=res.read()
                self.assertIn(b'Resume.Home',page)
                self.assertIn(b'src="/logo.png"',page)
            with urlopen(base+'/logo.png') as res:
                self.assertEqual(res.headers['Content-Type'],'image/png')
                self.assertTrue(res.read().startswith(b'\x89PNG\r\n\x1a\n'))
            data=json.dumps(dict(employer='Acme',role='Analyst',bullet='Automated Python reports')).encode()
            with urlopen(Request(base+'/api/version',data=data,headers={'Content-Type':'application/json','X-Resume-App':'1'})) as res:self.assertEqual(json.load(res)['number'],1)
            with self.assertRaises(HTTPError) as error:urlopen(Request(base+'/api/version',data=data,headers={'Content-Type':'application/json','X-Resume-App':'1','Origin':'https://evil.example'}))
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(HTTPError):urlopen(Request(base+'/api/version',data=data,headers={'Content-Type':'application/json'}))
            with urlopen(base+'/api/state') as res:self.assertEqual(len(json.load(res)['versions']),1)
            with urlopen(base+'/api/backup') as res:self.assertEqual(json.load(res)['schema_version'],4)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
