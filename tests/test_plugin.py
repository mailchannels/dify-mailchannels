import json
from pathlib import Path
import pytest
import requests
import responses
import yaml
from dify_plugin.core.entities.plugin.setup import PluginConfiguration
from dify_plugin.entities.tool import ToolProviderConfiguration
from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from provider.mailchannels import MailChannelsProvider
from tools.send_email import SendEmailTool

URL='https://api.mailchannels.net/tx/v1/send'
KEY='test-key-not-real'
CREDS={'api_key':KEY,'sender':'sender@example.com','allowed_recipients':'recipient@example.net','mode':'dry_run'}
INPUT={'to':'recipient@example.net','subject':'Update','text':'Private content'}

def invoke(params=None,**credentials):
    tool=SendEmailTool.from_credentials({**CREDS,**credentials})
    messages=list(tool.invoke(INPUT if params is None else params))
    assert len(messages)==1
    return messages[0].message.json_object

def sent(status='sent'):
    return {'request_id':'r','results':[{'index':0,'status':status,'message_id':'m','reason':KEY}]}

def test_sdk_schema():
    cfg=PluginConfiguration.model_validate(yaml.safe_load(Path('manifest.yaml').read_text()))
    provider=ToolProviderConfiguration.model_validate(yaml.safe_load(Path(cfg.plugins.tools[0]).read_text()))
    assert [p.name for p in provider.tools[0].parameters]==['to','subject','text','html']
    assert next(c for c in provider.credentials_schema if c.name=='api_key').type.value=='secret-input'

@responses.activate
def test_dry_run():
    responses.post(URL,json={'data':['private MIME']})
    assert invoke()=={'status':'validated','dry_run':True,'sent':False}
    req=responses.calls[0].request
    assert req.url==URL+'?dry-run=true'
    assert req.headers['X-Api-Key']==KEY
    body=json.loads(req.body)
    assert body['from']['email']==CREDS['sender']
    assert body['personalizations'][0]['to'][0]['email']==INPUT['to']

@responses.activate
def test_send_html():
    responses.post(URL,json=sent(),status=202)
    result=invoke({**INPUT,'html':'<p>Hello</p>'},mode='send')
    assert result['status']=='accepted'
    assert result['delivery_confirmed'] is False
    assert responses.calls[0].request.url==URL
    assert len(json.loads(responses.calls[0].request.body)['content'])==2

@responses.activate
def test_validation_never_sends():
    responses.post(URL,json={'data':['mime']})
    MailChannelsProvider().validate_credentials({**CREDS,'mode':'send'})
    req=responses.calls[0].request
    assert req.url==URL+'?dry-run=true'
    body=json.loads(req.body)
    assert body['from']['email']==body['personalizations'][0]['to'][0]['email']==CREDS['sender']

@pytest.mark.parametrize('extra',[{'mode':'send'},{'api_key':'other'},{'sender':'other@example.com'},{'to':'other@example.net'},{'to':'invalid'},{'subject':'Bad\r\nheader'},{'text':''}])
@responses.activate
def test_reject_before_network(extra):
    assert invoke({**INPUT,**extra})['status']=='rejected'
    assert not responses.calls

@pytest.mark.parametrize('status',[400,401,403,429,500,503])
@responses.activate
def test_api_error(status):
    responses.post(URL,json={'message':KEY},status=status)
    result=invoke(mode='send')
    assert result['status']=='unknown'
    assert result['retry_safe'] is False
    assert KEY not in json.dumps(result)
    assert len(responses.calls)==1

@responses.activate
def test_timeout():
    responses.post(URL,body=requests.Timeout(KEY))
    assert invoke(mode='send')['status']=='unknown'
    assert len(responses.calls)==1

@pytest.mark.parametrize('data,mode',[({},'send'),(sent(),'dry_run'),({'data':['mime']},'send')])
@responses.activate
def test_wrong_variant(data,mode):
    responses.post(URL,json=data)
    assert invoke(mode=mode)['status']=='unknown'

@responses.activate
def test_failed_result():
    responses.post(URL,json=sent('failed'),status=202)
    result=invoke(mode='send')
    assert result['status']=='failed'
    assert KEY not in json.dumps(result)

@responses.activate
def test_bad_credentials():
    responses.post(URL,json={'message':KEY},status=401)
    with pytest.raises(ToolProviderCredentialValidationError) as exc:
        MailChannelsProvider().validate_credentials(CREDS)
    assert KEY not in str(exc.value)

@pytest.mark.parametrize('extra',[{'api_key':''},{'sender':'bad'},{'mode':'other'},{'allowed_recipients':'bad'}])
@responses.activate
def test_invalid_configuration(extra):
    with pytest.raises(ToolProviderCredentialValidationError):
        MailChannelsProvider().validate_credentials({**CREDS,**extra})
    assert not responses.calls
