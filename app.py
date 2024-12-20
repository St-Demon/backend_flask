from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os
import re
from pymongo import MongoClient
import certifi
from datetime import datetime, timezone

# .env 파일 로드
load_dotenv()

app = Flask(__name__)
CORS(app, origins=["https://www.dongjinhub.store", "http://localhost:3000"], supports_credentials=True)

# OpenAI API 키 설정
api_key = os.getenv("OPENAI_ASSISTANT_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID_LIM")

client = OpenAI(api_key=api_key)

# MongoDB 연결 설정
mongo_uri = os.getenv("MONGODB")
mongo_client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
db = mongo_client["chat_database"]
collection = db["chat_messages"]

@app.route('/chat', methods=['POST'])
def send_message():
    user_message = request.json.get('message')

    if not user_message:
        return jsonify({"error": "메시지가 제공되지 않았습니다."}), 400
    
    try:

        # Thread 생성 시 시스템 메시지를 'user' 역할로 추가
        thread = client.beta.threads.create()

        thread_message = client.beta.threads.messages.create(
        thread.id,
        role="user",
        content=user_message,
        )
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )
     
        # 완료를 기다리며 폴링
        while True:
            run2 = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
            ) #스레드아이디와 runid가 같으면 status에서 completed(성공)일 때까지 기다려
            #status는 run의 현재 상태할 수 있음 
            if run2.status == "completed":
                break

        # 스레드 내의 모든 메시지를 가져와!!
        thread_messages = client.beta.threads.messages.list(thread.id)

        # assistant의 메시지만 가지고 와
        assistant_messages = [
            message for message in thread_messages.data
            if message.run_id == run.id and message.role == "assistant"
        ]

        # assistants에서도 마지막 메시지를 가져와라
        if assistant_messages: #한개 이상의 메시지가 있으면 트루
            last_assistant_message = assistant_messages[-1] #-1 마지막 항목을 가져오기 위한 특별한 인덱스입니다.
            response_content = ""
        else:
            response_content = "No response from assistant."

        if isinstance(last_assistant_message.content, list):
            for content_block in last_assistant_message.content:
                # TextContentBlock 내부 구조 접근
                if hasattr(content_block, "text") and hasattr(content_block.text, "value"):
                    response_content += content_block.text.value

        response_content = re.sub(r'【\d+:\d+†source】', '', response_content)
        response_content = re.sub(r'\[\d+:\d+\†source\]', '', response_content)
        print(response_content)

        # MongoDB에 질문과 응답 저장
        chat_data = {
            "user_message": user_message,
            "assistant_response": response_content.strip(),
            "timestamp": datetime.now(timezone.utc),
            "status": "success"  # 성공 상태
        }
        collection.insert_one(chat_data)

        # messages=[
        #     {"role": "system", "content": "모든 응답을 JSON 형식으로 출력하세요."},
        #     {"role": "user", "content": f"{response_content}, {user_message} 취업을 하기위해서 포토폴리오를 만들었어 사용자가 질문을 하면 나에 대해서 궁금할 것 같은 질문을 3개 추천해줘" },
        # ]
        messages = [
            {
                "role": "system",
                "content": (
                    "아래 예시와 정확히 동일한 JSON 형식으로만 응답하세요.\n"
                    "JSON 외의 다른 텍스트나 설명을 포함하지 마세요.\n\n"
                    "{\n"
                    "  \"추천질문\": [\n"
                    "    \"질문1\",\n"
                    "    \"질문2\",\n"
                    "    \"질문3\"\n"
                    "  ]\n"
                    "}"
                )
            },
            {
                "role": "user",
                "content": (
                    f"{response_content}, {user_message} 이 사용자에 대해서 궁금할만한 3가지 질문만 "
                    "\"추천질문\" 배열에 담아 JSON으로 반환하세요."
                )
            }
        ]

        suggestions_response = client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            response_format={"type": "json_object"},  # 올바른 response_format 설정
            max_tokens=150
        )
        suggestions_content = suggestions_response.choices[0].message.content
        print(suggestions_content)

        return jsonify({
            "response": response_content.strip(),
            "suggestions_content1": suggestions_content
        }), 200


    except Exception as e:
        # 오류 정보 저장
        error_data = {
            "user_message": user_message,
            "error_message": str(e),
            "timestamp": datetime.now(timezone.utc),
            "status": "error"  # 오류 상태
        }
        collection.insert_one(error_data)

        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
