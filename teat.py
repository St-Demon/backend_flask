from openai import AzureOpenAI
import time
import json
import os

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-05-01-preview",
    )

assistant = client.beta.assistants.create(
  name="여행 가이드 도우미",
  instructions="당신은 여행 가이드 전문가입니다. 지식 기반을 사용하여 여행에 필요한 정보 질문에 대해서 알려주세요.",
  model="gpt-4o",
  tools=[{"type": "file_search"}],
)
vector_store = client.beta.vector_stores.create(name="여행 가이드")

file_paths = ["/content/파리.pdf", "/content/대만.pdf"]

file_streams = [open(path, "rb") for path in file_paths]

file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
  vector_store_id=vector_store.id, files=file_streams
)

assistant = client.beta.assistants.update(
  assistant_id=assistant.id,
  tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}})

thread = client.beta.threads.create()

message = client.beta.threads.messages.create(
  thread_id=thread.id,
  role="user",
  content="이스탄불 뮤지엄패스가 뭐야?",
)

run = client.beta.threads.runs.create(
  thread_id=thread.id,
  assistant_id=assistant.id,
)

run = client.beta.threads.runs.retrieve(
  thread_id=thread.id,
  run_id=run.id
)

status = run.status

while status not in ["completed", "cancelled", "expired", "failed"]:
    time.sleep(5)
    run = client.beta.threads.runs.retrieve(thread_id=thread.id,run_id=run.id)
    status = run.status

messages = client.beta.threads.messages.list(
  thread_id=thread.id
)

result = messages.model_dump_json()

result_dict = json.loads(result)
print(result_dict["data"][0]["content"][0]["text"]["value"])