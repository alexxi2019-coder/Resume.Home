import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import Store, SCHEMA, CATEGORIES, ValidationError


PROFILE='''Summary
A short profile.
Experience
Example Co | Analyst | 2022 - Present
• Built Python reporting.
Education
Example University
Bachelor of Science in Finance
May 2021
Projects
Equity Model
• Built a valuation model with 5-year forecasts.
Technical Skills
Software: Python, SQL, Excel
Certifications
Finance Certificate
Interests
Running, photography
'''


class Categories(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'resume.sqlite3';self.s=Store(self.path)
    def tearDown(self):self.temp.cleanup()

    def test_every_category_revises_restores_and_persists(self):
        for category in CATEGORIES:
            payload=dict(category=category,title=category+' title',bullet='Original '+category,employer='School' if category=='education' else '',date_text='2020 – 2024')
            if category=='experience':payload.update(employer='Example',role='Analyst')
            a=self.s.save_version(payload)
            self.s.save_version(dict(payload,bullet='Updated '+category,accomplishment_id=a['id'],parent_id=a['version_id']))
            self.s.restore({'version_id':a['version_id']})
        state=Store(self.path).state()
        self.assertEqual(len(state['versions']),18)
        self.assertEqual({v['category'] for v in state['versions']},set(CATEGORIES))
        self.assertTrue(all(v['date_text']=='2020 – 2024' for v in state['versions']))

    def test_category_appropriate_validation(self):
        with self.assertRaises(ValidationError):self.s.save_version({'bullet':'Work with no employer or role'})
        for category in CATEGORIES[1:]:
            a=self.s.save_version(dict(category=category,title='Named entry',bullet='Supported wording'))
            self.assertEqual(a['number'],1)
            with self.assertRaises(ValidationError):self.s.save_version(dict(category=category,title='',bullet='Details'))
        with self.assertRaises(ValidationError):self.s.save_version(dict(category='imaginary',title='Test',bullet='Details'))

    def test_import_all_sections_without_invented_employers(self):
        p=self.s.preview_resume({'kind':'text','text':PROFILE})
        self.assertEqual({i['category'] for i in p['items']},set(CATEGORIES))
        selected=[]
        for i in p['items']:
            g=next(g for g in p['groups'] if g['id']==i['group_id'])
            selected.append(dict(i,action='new',category=g['category'],title=g['title'],employer=g['employer'],role=g['role'],employment_dates=g['employment_dates']))
        self.s.confirm_resume({'token':p['token'],'items':selected})
        state=self.s.state()
        self.assertEqual(len(state['versions']),6)
        project=next(v for v in state['versions'] if v['category']=='project')
        self.assertEqual(project['employer'],'');self.assertEqual(project['role'],'')
        self.assertEqual(project['title'],'Equity Model')
        self.assertEqual(len(state['provenance']),6)
        restored=Store(Path(self.temp.name)/'restored.sqlite3');restored.import_backup(self.s.backup())
        self.assertEqual(state,restored.state())

    def test_pre_category_database_and_schema2_backup_migrate_without_rewriting(self):
        old=Path(self.temp.name)/'legacy.sqlite3'
        db=sqlite3.connect(old);db.executescript(SCHEMA)
        a='a73093c7-d48c-4e0c-911c-76e09d854f75';v='b73093c7-d48c-4e0c-911c-76e09d854f75'
        db.execute('INSERT INTO accomplishments VALUES (?,?,NULL)',(a,'2020-01-01'))
        values=(v,a,1,None,'2020-01-01','original','Example','Analyst','','Unchanged original','','','[]','','',None)
        db.execute('INSERT INTO versions VALUES ('+','.join('?' for _ in values)+')',values)
        db.execute('UPDATE accomplishments SET preferred_version_id=? WHERE id=?',(v,a));db.commit();db.close()
        migrated=Store(old);entry=migrated.state()['versions'][0]
        self.assertEqual(entry['bullet'],'Unchanged original');self.assertEqual(entry['category'],'experience')
        self.assertEqual(entry['id'],v);self.assertEqual(migrated.state()['accomplishments'][0]['preferred_version_id'],v)
        backup=migrated.backup();backup['schema_version']=2
        for row in backup['data']['versions']:
            for key in ('category','title','date_text','location'):row.pop(key)
        self.s.import_backup(backup);self.assertEqual(self.s.state()['versions'][0],entry)

    def test_matching_and_sectioned_application_exports(self):
        skill=self.s.save_version(dict(category='skill',title='Python',bullet='Self-reported advanced proficiency'))
        interest=self.s.save_version(dict(category='interest',title='Kubernetes',bullet='Reading about Kubernetes'))
        job=self.s.save_job(dict(company='Example',title='Engineer',description='Required:\n- Python\n- Kubernetes'))['id']
        matched=self.s.matches(job,'keyword')['ranked']
        skills=next(m for m in matched if m['version']['id']==skill['version_id'])
        hobbies=next(m for m in matched if m['version']['id']==interest['version_id'])
        self.assertEqual(skills['evidence'][0]['label'],'partial evidence')
        self.assertTrue(all(e['label']=='no evidence' for e in hobbies['evidence']))
        app=self.s.save_application(dict(job_id=job,name='Complete resume',version_ids=[skill['version_id'],interest['version_id']]))['id']
        output=self.s.export_application(app,'md')
        self.assertIn('## Technical skills',output);self.assertIn('## Interests',output);self.assertIn('Python —',output)
        before=output
        self.s.save_version(dict(category='skill',title='Python',bullet='Changed details',accomplishment_id=skill['id'],parent_id=skill['version_id']))
        self.assertEqual(self.s.export_application(app,'md'),before)


if __name__=='__main__':unittest.main()
