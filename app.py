# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.server_api import ServerApi
import certifi, os, re, time, logging

# env
load_dotenv()

app = Flask(__name__)
CORS(app, origins=["https://www.dongjinhub.store", "http://localhost:3000"], supports_credentials=True)
logging.basicConfig(level=logging.INFO)

# OpenAI
API_KEY = os.getenv("OPENAI_ASSISTANT_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID_LIM")
client = OpenAI(api_key=API_KEY)

# MongoDB
MONGO_URI = os.getenv("MONGODB")
DB_NAME = os.getenv("DATABASE_NAME", "portfolio_chat")
COLL_NAME = os.getenv("COLLECTION_NAME", "chat_messages")

mongo = None
collection = None

def _mask_uri(u: str) -> str:
    if not u: 
        return ""
    try:
        # 비밀번호만 마스킹
        if "://" in u and "@" in u:
            prefix, rest = u.split("://", 1)
            cred_host = rest.split("@", 1)
            if len(cred_host) == 2:
                creds, host = cred_host
                if ":" in creds:
                    user, _ = creds.split(":", 1)
                    creds_masked = f"{user}:***"
                else:
                    creds_masked = "***"
                return f"{prefix}://{creds_masked}@{host}"
    except Exception:
        pass
    return u

def connect_mongo():
    """MongoDB 연결 (성공 시 전역 collection 설정)"""
    global mongo, collection
    if not MONGO_URI:
        app.logger.info("MongoDB 비활성화: MONGODB 환경변수가 없음")
        return

    app.logger.info(f"Mongo URI (masked) = {_mask_uri(MONGO_URI)}")
    try:
        mongo = MongoClient(
            MONGO_URI,
            server_api=ServerApi('1'),
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=7000,
        )
        # 연결/인증 확인
        pong = mongo.admin.command("ping")
        app.logger.info(f"Mongo ping OK => {pong}")

        db = mongo[DB_NAME]
        collection = db[COLL_NAME]

        # 인덱스(시간 정렬/조회용)
        try:
            collection.create_index("timestamp")
            collection.create_index("thread_id")
        except Exception as ie:
            app.logger.warning(f"인덱스 생성 경고(무시): {ie}")

    except Exception as e:
        app.logger.error(f"❌ MongoDB 연결 실패: {e}")
        mongo = None
        collection = None

def save_chat(user_message: str, ai_response: str, thread_id: str | None):
    """정상 응답 저장"""
    if collection is None:
        return False
    doc = {
        "user_message": user_message,
        "assistant_response": ai_response,
        "thread_id": thread_id,
        "timestamp": datetime.now(timezone.utc),
        "status": "success",
    }
    try:
        collection.insert_one(doc)
        return True
    except Exception as e:
        app.logger.warning(f"Mongo 저장 실패(무시): {e}")
        return False

def save_error(user_message: str, err_msg: str, thread_id: str | None):
    """에러 로그 저장"""
    if collection is None:
        return False
    doc = {
        "user_message": user_message,
        "error_message": err_msg,
        "thread_id": thread_id,
        "timestamp": datetime.now(timezone.utc),
        "status": "error",
    }
    try:
        collection.insert_one(doc)
        return True
    except Exception as e:
        app.logger.warning(f"Mongo 오류 로그 저장 실패(무시): {e}")
        return False

# 앱 시작 시 1회 연결
connect_mongo()

# -------- 유틸 --------
def clean_sources(text: str) -> str:
    text = re.sub(r'【\d+:\d+†source】', '', text or '')
    text = re.sub(r'\[\d+:\d+†source\]', '', text or '')
    return (text or '').strip()

# -------- API --------
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "메시지가 제공되지 않았습니다."}), 400

    thread_id = None
    try:
        # Assistants 실행
        thread = client.beta.threads.create()
        thread_id = thread.id

        client.beta.threads.messages.create(thread.id, role="user", content=user_message)
        run = client.beta.threads.runs.create(thread_id=thread.id, assistant_id=ASSISTANT_ID)

        # 폴링
        deadline = time.time() + 60
        while True:
            r = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            if r.status == "completed":
                break
            if r.status in ("failed", "cancelled", "expired") or time.time() > deadline:
                err = f"assistant run {r.status}"
                save_error(user_message, err, thread_id)
                return jsonify({"error": err}), 500
            time.sleep(0.25)

        # 응답 추출
        msgs = client.beta.threads.messages.list(thread.id).data
        msgs = [m for m in msgs if m.run_id == run.id and m.role == "assistant"]
        content = ""
        if msgs:
            for block in (msgs[-1].content or []):
                if getattr(block, "text", None) and getattr(block.text, "value", None):
                    content += block.text.value
        response_text = clean_sources(content) or "No response from assistant."

        # 저장
        save_chat(user_message, response_text, thread_id)

        # 추천질문(JSON만)
        sys_prompt = '아래 예시와 동일한 JSON으로만 응답하세요.\n{"추천질문": ["질문1","질문2","질문3"]}'
        follow = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f'{response_text}, {user_message} 이 사용자에 대해 궁금한 3가지를 "추천질문" 배열 JSON으로만 반환'},
        ]
        suggestions = "{}"
        try:
            sres = client.chat.completions.create(
                model="gpt-3.5-turbo-1106",
                messages=follow,
                response_format={"type": "json_object"},
                max_tokens=150,
            )
            suggestions = sres.choices[0].message.content
        except Exception as se:
            app.logger.warning(f"추천질문 생성 실패(무시): {se}")

        return jsonify({"response": response_text, "suggestions_content1": suggestions}), 200

    except Exception as e:
        save_error(user_message, str(e), thread_id)
        return jsonify({"error": str(e)}), 500

# 헬스 체크
@app.route("/health", methods=["GET"])
def health():
    mongo_status = "not_initialized" if collection is None else "ok"
    return jsonify({"ok": True, "mongo": mongo_status}), 200

if __name__ == "__main__":
    # 개발 서버
    app.run(host="0.0.0.0", port=5000, debug=True)
