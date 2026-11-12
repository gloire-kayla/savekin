# Elastic setup for SaveKin

The integration code is ready, but no Elastic account credentials were available during development. API requests and error handling are mock-tested; a real managed-model response remains unverified. No account, project, API key or agent was created remotely by the assistant.

## Your part: account and access

1. Open the [PayPal hackathon Elastic offer](https://paypalaihackathon.devpost.com/details/elastic) and follow its signup link. Create an Elasticsearch Serverless project. Keep its managed model available for Agent Builder. Trial limits apply; arrange access through judging rather than assuming the trial lasts indefinitely.
2. Open the project and find its **Kibana HTTPS endpoint**. Use the Kibana URL, not the Elasticsearch endpoint or an `/app/...` browser page. The default space needs no suffix; another space can use `/s/space-id`.
3. In Kibana, find **API keys → Create API key → Control security privileges**. Create a temporary setup key using the role descriptor from `elastic-setup-role.json`. Create a separate runtime key using `elastic-runtime-role.json`. Copy each key's **encoded** value privately when shown. These files contain permissions, not secrets. If using another space, replace `space:default` in both files first. Your signed-in Elastic user must have the permissions it grants. See [Elastic's API key instructions](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/api-keys).

The setup key manages agents and is used only for setup. The runtime key reads Agent Builder and connectors, monitors inference and has no index permissions. Do not use an unrestricted project/admin key for the running helper. Elastic may supply built-in HTTP API tools even when optional tools are disabled; key privileges remain important. SaveKin gives Elastic no PayPal credentials, payment endpoints or group-editing tools.

## Create the helper once

From the SaveKin project directory:

```powershell
& "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe" .\elastic_setup.py
```

Enter the Kibana URL, accept agent ID `savekin-helper`, and enter the temporary setup key at the hidden prompt. The script creates a dedicated helper using the SaveKin product guide and planning instructions, with optional Elastic capabilities and custom tools disabled. Existing unrelated agents are not overwritten. No API key is saved to disk. Revoke the temporary setup key after setup through your Elastic account.

## Start SaveKin with Elastic

```powershell
& "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe" .\start_sandbox.py --restart-local --with-elastic
```

Enter your existing PayPal sandbox credentials as usual. Then enter the Kibana URL, the same agent ID and the separate **runtime** key at its hidden prompt. The launcher checks access to the agent before replacing a running local server; failed setup leaves that server running. A successful agent-access check is not a generated-reply test.

No OpenAI key or model ID is needed for this Elastic path. The server selects Elastic's managed-model routing through Agent Builder. `--with-ai` remains the OpenAI option; choose one flag, not both.

## Verify one real reply

Refresh SaveKin with Ctrl+F5, open SaveKin helper, check the provider label and accept the data-sharing notice. Ask “We are five friends saving USD 10 each monthly. Help us choose a goal and compare a one-time target with a repeating cycle.” Follow up with “Give us a roadmap with your assumptions.”

This uses model quota and sends the product guide, your message, recent chat history and limited selected-group context to Elastic. General chat sends no selected-group records. The local transcript stays private to the signed-in SaveKin account. Elastic creates provider-side conversations; this path does not support OpenAI's `store:false`. Local deletion does not delete remote provider records. Avoid sensitive details in messages and do not treat the Elastic deployment as a separate user-isolated vault: its authorized administrators may access provider-side data.

The backend passes recent local history explicitly and never reuses an Elastic conversation ID across local users. Runtime instruction overrides keep the SaveKin guide current. No document index or semantic-search pipeline is created in this version; Agent Builder receives the guide as context. Adding searchable knowledge retrieval is a separate optional enhancement.

## Troubleshooting

- **404:** check that the endpoint is Kibana and that the helper exists in the selected space.
- **401/403:** check the encoded key value, its owner, expiry and requested privileges.
- **Access check passes but chat fails:** verify the trial/model quota and managed model availability, and check that your deployment supports Agent Builder runtime configuration overrides.
- **AI unavailable:** ensure the server was restarted using `--with-elastic`; refreshing the website alone does not change server credentials.

Do not paste keys into chat, frontend/mobile code, a public repository, or screenshots. Keep the server terminal open while reviewing.

Implementation references: [Converse API](https://www.elastic.co/docs/api/doc/kibana/operation/operation-post-agent-builder-converse), [Create agent API](https://www.elastic.co/docs/api/doc/kibana/operation/operation-post-agent-builder-agents), [managed models](https://www.elastic.co/docs/explore-analyze/ai-features/agent-builder/models).
