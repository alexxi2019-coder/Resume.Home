#!/usr/bin/env python3
"""Seed fictional examples into an explicitly separate demo database only."""
from app import ROOT, Store

path = ROOT/'data'/'demo.sqlite3'
s = Store(path)
if s.state()['accomplishments'] or s.state()['jobs']:
    print('Demo database already contains data; nothing changed.')
else:
    a=s.save_version(dict(employer='Northstar (fictional)',role='Operations Analyst',project='Reporting workflow',bullet='Automated weekly Python reporting, reducing preparation time from 10 hours to 2.',tags=['Python','Automation','Reporting'],metrics='Fictional example only: 8 hours saved per week.',context='Demo data; do not use as a real accomplishment.',note='Fictional demo v1'))
    s.save_version(dict(accomplishment_id=a['id'],parent_id=a['version_id'],employer='Northstar (fictional)',role='Operations Analyst',project='Reporting workflow',bullet='Built a Python reporting workflow that saved 8 hours of weekly preparation.',tags=['Python','Automation'],metrics='Fictional example only: 8 hours weekly.',context='Demo data only.',note='Lead with the implementation',preferred=True))
    s.save_version(dict(employer='Northstar (fictional)',role='Operations Analyst',project='Customer reporting',bullet='Partnered with sales and support to build SQL dashboards tracking customer response times.',tags=['SQL','Collaboration'],context='Entirely fictional demo example.',note='Initial demo version'))
    s.save_job(dict(company='Example Company (fictional)',title='Business Operations Analyst',description='Required qualifications:\n- Python automation\n- SQL\n- At least 3 years of analytics experience\nPreferred qualifications:\n- Collaboration\n- Tableau'))
    print('Fictional examples created in ' + str(path))
print('Launch separately: python3 app.py --db data/demo.sqlite3 --port 8766')
