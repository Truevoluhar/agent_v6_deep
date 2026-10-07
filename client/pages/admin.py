from __future__ import annotations

import os
import sys
from pathlib import Path
import requests
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from client.auth import require_login, with_guid
from client.service_urls import resolve_agent_api_url

st.set_page_config(page_title='Uporabniki', layout='wide')
guid,user=require_login()
if user['role']!='admin':
    st.error('Dostop zavrnjen')
    st.stop()
st.page_link('app.py',label='Nazaj na klepet')
st.title('Uporabniki')
base=f'{resolve_agent_api_url()}/v1/admin/users'
try:
    response=requests.get(base,params=with_guid(),timeout=30)
    response.raise_for_status()
    users=response.json()
except requests.RequestException as exc:
    st.error(f'Uporabnikov ni bilo mogoče naložiti: {exc}')
    st.stop()
st.dataframe([{k:v for k,v in item.items() if k in ('user_id','username','role','is_active')} for item in users],hide_index=True)
with st.form('new_user'):
    st.subheader('Nov uporabnik')
    username=st.text_input('Uporabniško ime')
    password=st.text_input('Geslo',type='password')
    role=st.selectbox('Vloga',['user','admin'])
    submitted=st.form_submit_button('Ustvari')
if submitted:
    response=requests.post(base,params=with_guid(),json={'username':username,'password':password,'role':role},timeout=30)
    if response.ok: st.rerun()
    else: st.error(response.text)
for item in users:
    with st.expander(item['username']):
        new_role=st.selectbox('Vloga',['user','admin'],index=0 if item['role']=='user' else 1,key=f"role:{item['user_id']}")
        active=st.checkbox('Aktiven',value=item['is_active'],key=f"active:{item['user_id']}")
        if item['user_id']==user['user_id'] and not active:
            st.warning('Če deaktivirate svoj račun, boste odjavljeni.')
        if st.button('Shrani',key=f"save:{item['user_id']}"):
            response=requests.patch(f"{base}/{item['user_id']}",params=with_guid(),json={'role':new_role,'is_active':active},timeout=30)
            if response.ok: st.rerun()
            else: st.error(response.text)
        if os.environ.get('AUTH_MODE','local')=='local':
            new_password=st.text_input('Novo geslo',type='password',key=f"password:{item['user_id']}")
            if st.button('Ponastavi geslo',key=f"reset:{item['user_id']}") and new_password:
                response=requests.post(f"{base}/{item['user_id']}/reset-password",params=with_guid(),json={'password':new_password},timeout=30)
                if response.ok: st.success('Geslo je spremenjeno')
                else: st.error(response.text)
