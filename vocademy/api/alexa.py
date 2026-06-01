from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import re
import random

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def supabase_get(endpoint):
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    })
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode())


def get_active_session():
    data = supabase_get(
        "sessions?select=id,kid_id,status,file_id,kids(id,name)&status=eq.active&order=created_at.desc&limit=1"
    )
    if not data:
        return None, None, None, None
    session = data[0]
    kid_id = session["kid_id"]
    kid_name = session["kids"]["name"]
    session_id = session["id"]
    file_id = session.get("file_id")
    return kid_id, kid_name, session_id, file_id


def get_quiz_for_session(session_id):
    data = supabase_get(
        f"quizzes?select=*&session_id=eq.{session_id}&limit=1"
    )
    if not data:
        return None
    return data[0]["questions"]


def get_document_from_url(file_id):
    try:
        data = supabase_get(f"files?select=*&id=eq.{file_id}")
        if not data:
            return None
        content = data[0].get("content")
        return content[:3000] if content else None
    except Exception:
        return None


def chunk_document(text, chunk_size=300):
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= chunk_size:
            current += (" " if current else "") + sentence
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks if chunks else [text]


def clean_answer(raw):
    """Extract only the first letter A/B/C/D from the answer slot."""
    cleaned = ''.join(filter(str.isalpha, raw)).upper()
    return cleaned[:1] if cleaned else ""


def explain_word(word):
    """Explain a word using AI with multiple model fallbacks."""
    OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
    prompt = f"Explain '{word}' in 1-2 simple fun sentences for a young child. Be clear and easy to understand."

    # FIX: Multiple model fallbacks instead of single deprecated model
    models = [
        "mistralai/mistral-7b-instruct:free",
        "google/gemma-3-4b-it:free",
        "meta-llama/llama-3.2-3b-instruct:free",
    ]

    for model in models:
        try:
            payload = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 80
            }).encode()
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json"
                }
            )
            # FIX: Increased timeout from 5s to 10s for free models
            res = urllib.request.urlopen(req, timeout=10)
            result = json.loads(res.read().decode())
            return result["choices"][0]["message"]["content"]
        except Exception:
            continue

    # FIX: Fallback if all models fail
    return f"'{word}' is a really interesting word! Ask your teacher to explain it to you after the lesson!"


def save_results(session_id, kid_id, rapport, score, feedback, manques):
    data = json.dumps({
        "session_id": session_id,
        "kid_id": kid_id,
        "rapport": rapport,
        "score": score,
        "feedback": feedback,
        "manques": json.dumps(manques)
    }).encode()

    url = f"{SUPABASE_URL}/rest/v1/results"
    req = urllib.request.Request(url, data=data, headers={
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    })
    req.get_method = lambda: "POST"
    urllib.request.urlopen(req)


def safe_finish_quiz(kid_name, kid_id, session_id, questions, user_answers, score, feedback):
    total = len(questions)
    if score == total:
        ending = "PERFECT SCORE! You are absolutely incredible!"
    elif score >= total // 2:
        ending = "Great job! You should be super proud of yourself!"
    else:
        ending = "Good effort! Keep practicing and you will be a champion!"

    closing = (
        f"{feedback} "
        f"And that is the end of the quiz! "
        f"{kid_name} you scored {score} out of {total}! "
        f"{ending} "
        f"Your report has been saved. "
        f"See you next time! Bye bye!"
    )

    # Generate report with AI, with multiple model fallbacks
    report = None
    missed = []

    try:
        OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY")
        missed = [q["question"] for i, q in enumerate(questions)
                  if i >= len(user_answers) or user_answers[i] != q["answer"]]

        prompt = f"{kid_name} scored {score}/{total}. Write 2 fun encouraging sentences for a child. Plain text only."

        # FIX: Updated models — removed deprecated nvidia/nemotron, added reliable free models
        models = [
            "mistralai/mistral-7b-instruct:free",
            "google/gemma-3-4b-it:free",
            "meta-llama/llama-3.2-3b-instruct:free",
        ]

        for model in models:
            try:
                payload = json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 60
                }).encode()
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "Content-Type": "application/json"
                    }
                )
                # FIX: Increased timeout from 6s to 10s for free models
                res = urllib.request.urlopen(req, timeout=10)
                result = json.loads(res.read().decode())
                report = result["choices"][0]["message"]["content"]
                break
            except Exception:
                continue

        if not report:
            report = f"{kid_name} scored {score} out of {total}. Great effort and keep it up!"

    except Exception as e:
        print(f"REPORT GENERATION ERROR: {str(e)}")
        report = f"{kid_name} scored {score} out of {total}. Amazing effort!"
        missed = []

    # FIX: Log save errors instead of silently swallowing them
    try:
        save_results(session_id, kid_id, report, score, feedback, missed)
    except Exception as e:
        print(f"SAVE RESULTS ERROR: session={session_id} kid={kid_id} error={str(e)}")
        # Still return closing speech so the kid hears the ending
        # but update message to reflect save issue
        closing = closing.replace(
            "Your report has been saved.",
            "Keep up the great work!"
        )

    return closing


def build_response(speech, attributes=None, end=False, reprompt=None):
    response = {
        "version": "1.0",
        "sessionAttributes": attributes or {},
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": speech
            },
            "shouldEndSession": end
        }
    }
    if reprompt:
        response["response"]["reprompt"] = {
            "outputSpeech": {
                "type": "PlainText",
                "text": reprompt
            }
        }
    return response


def ask_question(questions, index, prefix=""):
    q = questions[index]
    speech = (
        f"{prefix} "
        f"Question {index + 1} out of {len(questions)}: {q['question']}. "
        f"Is it  A: {q['options']['A']}. "
        f"B: {q['options']['B']}. "
        f"C: {q['options']['C']}. "
        f"Or D: {q['options']['D']}. "
        f"What do you think?"
    )
    return speech


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers['Content-Length'])
            body = json.loads(self.rfile.read(length).decode())

            req_type = body["request"]["type"]
            attributes = body.get("session", {}).get("attributes", {})

            # ── Launch ──────────────────────────────────────────────────────
            if req_type == "LaunchRequest":
                try:
                    kid_id, kid_name, session_id, file_id = get_active_session()
                    if not kid_id:
                        res = build_response(
                            "Hmm, I could not find any active session. "
                            "Please select a kid in the app first!",
                            end=True
                        )
                    else:
                        attributes["kid_id"] = kid_id
                        attributes["kid_name"] = kid_name
                        attributes["session_id"] = session_id
                        attributes["file_id"] = file_id
                        attributes["mode"] = "menu"
                        res = build_response(
                            f"Hey hey hey! Welcome {kid_name}! "
                            f"I am so excited to learn with you today! "
                            f"You can say read the document to listen to today's lesson, "
                            f"or say start the quiz if you feel ready to show off what you know! "
                            f"What do you want to do?",
                            attributes,
                            reprompt="Say read the document or start the quiz!"
                        )
                except Exception as e:
                    res = build_response(
                        f"Oops! Something went wrong: {str(e)}",
                        end=True
                    )

            # ── Intent Requests ─────────────────────────────────────────────
            elif req_type == "IntentRequest":
                intent = body["request"]["intent"]["name"]
                slots = body["request"]["intent"].get("slots", {})

                # Read Document
                if intent == "ReadDocumentIntent":
                    file_id = attributes.get("file_id")
                    kid_name = attributes.get("kid_name", "friend")

                    if not file_id:
                        res = build_response(
                            "Hmm I could not find any document for this session. "
                            "Please ask your teacher to upload one!",
                            attributes,
                            reprompt="Say start the quiz to begin!"
                        )
                    else:
                        try:
                            document = get_document_from_url(file_id)
                            if not document:
                                res = build_response(
                                    "I could not load the document right now. "
                                    "Let us go straight to the quiz instead! "
                                    "Say start the quiz when you are ready!",
                                    attributes,
                                    reprompt="Say start the quiz!"
                                )
                            else:
                                chunks = chunk_document(document)
                                attributes["chunks"] = chunks
                                attributes["chunk_index"] = 0
                                attributes["mode"] = "reading"
                                attributes["paused"] = False

                                first_chunk = chunks[0]
                                more = len(chunks) > 1

                                res = build_response(
                                    f"Awesome {kid_name}! Let me read today's lesson for you. "
                                    f"Listen carefully because there will be a quiz after! "
                                    f"Here we go! "
                                    f"{first_chunk} "
                                    f"{'Did you understand everything? Say any word you need help with, or say continue!' if more else 'That was the whole lesson! Say start the quiz when you feel ready!'}",
                                    attributes,
                                    reprompt="Say a word you need help with, or say continue!"
                                )
                        except Exception as e:
                            res = build_response(
                                f"Error loading document: {str(e)}",
                                attributes,
                                reprompt="Say start the quiz!"
                            )

                # Start Quiz
                elif intent in ["StartQuizIntent", "GetDataIntent"]:
                    if not attributes.get("kid_id"):
                        res = build_response(
                            "Please select a kid in the app first!",
                            end=True
                        )
                    else:
                        try:
                            kid_name = attributes.get("kid_name", "friend")
                            session_id = attributes.get("session_id")

                            questions = get_quiz_for_session(session_id)

                            if not questions:
                                res = build_response(
                                    "I could not find a quiz for this session. "
                                    "Please ask your teacher to create one first!",
                                    end=True
                                )
                            else:
                                attributes["questions"] = questions
                                attributes["index"] = 0
                                attributes["score"] = 0
                                attributes["user_answers"] = []
                                attributes["mode"] = "quiz"
                                attributes["paused"] = False

                                speech = ask_question(
                                    questions, 0,
                                    prefix=(
                                        f"Woohoo! Let us do this {kid_name}! "
                                        f"There are {len(questions)} questions. "
                                        f"Do your best and have fun! "
                                        f"Remember you can say repeat anytime "
                                        f"and I will say the question again! "
                                        f"Here is your first question!"
                                    )
                                )
                                res = build_response(
                                    speech, attributes,
                                    reprompt="Say A, B, C or D!"
                                )
                        except Exception as e:
                            res = build_response(
                                f"Error loading quiz: {str(e)}",
                                end=True
                            )

                # Answer
                elif intent == "AnswerIntent":
                    questions = attributes.get("questions")
                    if not questions:
                        res = build_response(
                            "Say start the quiz to begin!",
                            attributes,
                            reprompt="Say start the quiz!"
                        )
                    else:
                        index = attributes.get("index", 0)
                        question = questions[index]
                        raw = slots.get("answer", {}).get("value", "")
                        user_answer = clean_answer(raw)

                        # FIX: If slot was empty/unrecognized, try extracting from
                        # the raw transcript field Alexa sometimes provides
                        if not user_answer or user_answer not in ["A", "B", "C", "D"]:
                            try:
                                transcript = body["request"].get("intent", {}).get(
                                    "slots", {}).get("answer", {}).get(
                                    "resolutions", {}).get(
                                    "resolutionsPerAuthority", [{}])[0].get(
                                    "values", [{}])[0].get("value", {}).get("name", "")
                                user_answer = clean_answer(transcript)
                            except Exception:
                                pass

                        correct_answer = question["answer"].upper()

                        user_answers = attributes.get("user_answers", [])
                        user_answers.append(user_answer)
                        attributes["user_answers"] = user_answers

                        if user_answer == correct_answer:
                            attributes["score"] = attributes.get("score", 0) + 1
                            feedbacks = [
                                "Boom! That is correct! You are on fire!",
                                "Yes yes yes! Amazing answer!",
                                "Correct! You are so smart!",
                                "Nailed it! Keep going superstar!",
                                "Woohoo! That is right!"
                            ]
                            feedback = random.choice(feedbacks)
                        else:
                            correct_text = question["options"][correct_answer]
                            feedback = (
                                f"Oops! Not quite! "
                                f"The correct answer was {correct_answer}: {correct_text}. "
                                f"Do not worry, you will get the next one!"
                            )

                        next_index = index + 1

                        if next_index >= len(questions):
                            score = attributes.get("score", 0)
                            kid_name = attributes.get("kid_name", "friend")
                            kid_id = attributes.get("kid_id")
                            session_id = attributes.get("session_id")

                            closing = safe_finish_quiz(
                                kid_name, kid_id, session_id,
                                questions, user_answers, score, feedback
                            )
                            res = build_response(closing, end=True)
                        else:
                            attributes["index"] = next_index
                            speech = ask_question(
                                questions, next_index,
                                prefix=feedback
                            )
                            res = build_response(
                                speech, attributes,
                                reprompt="Say A, B, C or D!"
                            )

                # Explain / Define Intent
                elif intent == "ExplainIntent":
                    word = slots.get("word", {}).get("value", "")
                    mode = attributes.get("mode", "menu")
                    kid_name = attributes.get("kid_name", "friend")

                    if not word:
                        res = build_response(
                            "Hmm I did not catch that! Try saying what is a castle or explain rocket!",
                            attributes,
                            reprompt="What word do you want me to explain?"
                        )
                    else:
                        try:
                            explanation = explain_word(word)

                            if mode == "quiz":
                                attributes["pre_explain_mode"] = "quiz"
                                res = build_response(
                                    f"Great question {kid_name}! {explanation} "
                                    f"Say proceed when you are ready to continue the quiz!",
                                    attributes,
                                    reprompt="Say proceed to continue the quiz!"
                                )
                            elif mode == "reading":
                                attributes["pre_explain_mode"] = "reading"
                                res = build_response(
                                    f"Great question {kid_name}! {explanation} "
                                    f"Say proceed when you are ready to continue the lesson!",
                                    attributes,
                                    reprompt="Say proceed to continue!"
                                )
                            else:
                                res = build_response(
                                    f"Great question! {explanation} "
                                    f"Say read the document or start the quiz to continue!",
                                    attributes,
                                    reprompt="Say read the document or start the quiz!"
                                )

                        except Exception as e:
                            res = build_response(
                                f"Explain error: {str(e)}",
                                attributes,
                                reprompt="Say continue!"
                            )

                # Repeat Intent
                elif intent == "RepeatIntent":
                    mode = attributes.get("mode", "menu")

                    if mode == "quiz":
                        questions = attributes.get("questions")
                        index = attributes.get("index", 0)
                        if questions:
                            speech = ask_question(
                                questions, index,
                                prefix="Sure! Let me repeat that for you!"
                            )
                            res = build_response(
                                speech, attributes,
                                reprompt="Say A, B, C or D!"
                            )
                        else:
                            res = build_response(
                                "There is no question to repeat right now. "
                                "Say start the quiz to begin!",
                                attributes,
                                reprompt="Say start the quiz!"
                            )

                    elif mode == "reading":
                        chunks = attributes.get("chunks", [])
                        chunk_index = attributes.get("chunk_index", 0)
                        if chunks and chunk_index < len(chunks):
                            res = build_response(
                                f"Sure! Let me repeat that part! "
                                f"{chunks[chunk_index]} "
                                f"Did you understand everything? Say any word you need help with, or say continue!",
                                attributes,
                                reprompt="Say a word you need help with, or say continue!"
                            )
                        else:
                            res = build_response(
                                "There is no document to repeat. "
                                "Say read the document first!",
                                attributes,
                                reprompt="Say read the document!"
                            )
                    else:
                        res = build_response(
                            "Hmm there is nothing to repeat right now! "
                            "Say read the document or start the quiz!",
                            attributes,
                            reprompt="Say start the quiz!"
                        )

                # Score Intent
                elif intent == "ScoreIntent":
                    score = attributes.get("score", 0)
                    index = attributes.get("index", 0)
                    questions = attributes.get("questions", [])
                    kid_name = attributes.get("kid_name", "friend")
                    mode = attributes.get("mode", "menu")

                    if not questions:
                        res = build_response(
                            "You have not started the quiz yet! "
                            "Say start the quiz to begin!",
                            attributes,
                            reprompt="Say start the quiz!"
                        )
                    else:
                        questions_answered = index
                        remaining = len(questions) - index
                        if score == questions_answered and questions_answered > 0:
                            comment = "Perfect score so far! You are crushing it!"
                        elif questions_answered > 0 and score >= questions_answered // 2:
                            comment = "You are doing great! Keep it up!"
                        elif questions_answered > 0:
                            comment = "Keep trying! You can do it!"
                        else:
                            comment = "The quiz just started! Give it your best shot!"

                        if mode == "quiz":
                            current_question = ask_question(
                                questions, index,
                                prefix="Now let us keep going!"
                            )
                            res = build_response(
                                f"Here is your score {kid_name}! "
                                f"You have answered {questions_answered} questions "
                                f"and got {score} correct! "
                                f"{comment} "
                                f"You still have {remaining} questions to go! "
                                f"{current_question}",
                                attributes,
                                reprompt="Say A, B, C or D!"
                            )
                        elif mode == "reading":
                            res = build_response(
                                f"Here is your score {kid_name}! "
                                f"You have answered {questions_answered} questions "
                                f"and got {score} correct! "
                                f"{comment} "
                                f"Say continue to keep reading the lesson!",
                                attributes,
                                reprompt="Say continue or start the quiz!"
                            )
                        else:
                            res = build_response(
                                f"Here is your score {kid_name}! "
                                f"You have answered {questions_answered} questions "
                                f"and got {score} correct! "
                                f"{comment}",
                                attributes,
                                reprompt="Say start the quiz or read the document!"
                            )

                # Help
                elif intent == "AMAZON.HelpIntent":
                    res = build_response(
                        "No worries! Here is what you can do! "
                        "Say read the document to listen to today's lesson. "
                        "Say continue to move to the next part of the lesson. "
                        "Say start the quiz to answer questions. "
                        "Say repeat if you want me to say something again. "
                        "Say what is my score to check how you are doing. "
                        "Say what is a word to get an explanation of anything! "
                        "Say stop or pause to pause, and continue to resume. "
                        "And say A, B, C or D to answer questions! "
                        "You have got this!",
                        attributes,
                        reprompt="What would you like to do?"
                    )

                # Pause Intent
                elif intent == "AMAZON.PauseIntent":
                    kid_name = attributes.get("kid_name", "friend")
                    mode = attributes.get("mode", "menu")

                    if mode == "quiz":
                        attributes["paused"] = True
                        res = build_response(
                            f"Okay {kid_name}! Pausing the quiz here. "
                            f"Say continue whenever you are ready to keep going!",
                            attributes,
                            end=False,
                            reprompt="Say continue to keep going!"
                        )
                    elif mode == "reading":
                        attributes["paused"] = True
                        attributes["paused_before_resume"] = True
                        res = build_response(
                            f"Okay {kid_name}! Pausing the lesson here. "
                            f"Say continue to pick up right where we left off!",
                            attributes,
                            end=False,
                            reprompt="Say continue to keep going!"
                        )
                    else:
                        res = build_response(
                            f"No problem {kid_name}! There is nothing active right now. "
                            f"Say read the document or start the quiz when you are ready!",
                            attributes,
                            end=False,
                            reprompt="Say read the document or start the quiz!"
                        )

                # Stop Intent
                elif intent == "AMAZON.StopIntent":
                    kid_name = attributes.get("kid_name", "friend")
                    res = build_response(
                        f"Okay {kid_name}! See you next time! "
                        f"Keep being awesome! Bye bye!",
                        end=True
                    )

                # Cancel Intent
                elif intent == "AMAZON.CancelIntent":
                    kid_name = attributes.get("kid_name", "friend")
                    res = build_response(
                        f"Okay {kid_name}! See you next time! "
                        f"Keep being awesome! Bye bye!",
                        end=True
                    )

                # Continue / Resume / Proceed Intent
                elif intent in ["AMAZON.ResumeIntent", "ProceedIntent", "ContinueIntent"]:
                    mode = attributes.get("mode", "menu")
                    kid_name = attributes.get("kid_name", "friend")
                    pre_explain_mode = attributes.get("pre_explain_mode")

                    # Returning from an explanation in quiz
                    if pre_explain_mode == "quiz":
                        attributes["pre_explain_mode"] = None
                        questions = attributes.get("questions")
                        index = attributes.get("index", 0)
                        if questions:
                            speech = ask_question(
                                questions, index,
                                prefix=f"Welcome back {kid_name}! Let us continue the quiz!"
                            )
                            res = build_response(
                                speech, attributes,
                                reprompt="Say A, B, C or D!"
                            )
                        else:
                            res = build_response(
                                "No quiz in progress. Say start the quiz to begin!",
                                attributes,
                                reprompt="Say start the quiz!"
                            )

                    # Returning from an explanation in reading
                    elif pre_explain_mode == "reading":
                        attributes["pre_explain_mode"] = None
                        chunks = attributes.get("chunks", [])
                        chunk_index = attributes.get("chunk_index", 0)
                        if chunks and chunk_index < len(chunks):
                            remaining = len(chunks) - chunk_index - 1
                            res = build_response(
                                f"Welcome back {kid_name}! Continuing the lesson! "
                                f"{chunks[chunk_index]} "
                                f"{'Did you understand everything? Say any word you need help with, or say continue!' if remaining > 0 else 'That was the last part! Say start the quiz when you are ready!'}",
                                attributes,
                                reprompt="Say a word you need help with, or say continue!"
                            )
                        else:
                            res = build_response(
                                f"That was the end of the lesson {kid_name}! "
                                f"Say start the quiz when you are ready!",
                                attributes,
                                reprompt="Say start the quiz!"
                            )

                    # Continuing reading (next chunk)
                    elif mode == "reading":
                        chunks = attributes.get("chunks", [])
                        chunk_index = attributes.get("chunk_index", 0)
                        attributes["paused"] = False

                        was_paused = attributes.get("paused_before_resume", False)
                        if not was_paused:
                            chunk_index += 1
                            attributes["chunk_index"] = chunk_index
                        attributes["paused_before_resume"] = False

                        if not chunks or chunk_index >= len(chunks):
                            res = build_response(
                                f"That was the end of the lesson {kid_name}! "
                                f"Say start the quiz when you are ready!",
                                attributes,
                                reprompt="Say start the quiz!"
                            )
                        else:
                            remaining = len(chunks) - chunk_index - 1
                            res = build_response(
                                f"{'Welcome back! Continuing the lesson! ' if was_paused else ''}"
                                f"{chunks[chunk_index]} "
                                f"{'Did you understand everything? Say any word you need help with, or say continue!' if remaining > 0 else 'That was the last part! Say start the quiz when you are ready!'}",
                                attributes,
                                reprompt="Say a word you need help with, or say continue!"
                            )

                    # Continuing quiz after pause
                    elif mode == "quiz":
                        attributes["paused"] = False
                        questions = attributes.get("questions")
                        index = attributes.get("index", 0)

                        if questions:
                            speech = ask_question(
                                questions, index,
                                prefix=f"Welcome back {kid_name}! Let us continue!"
                            )
                            res = build_response(
                                speech, attributes,
                                reprompt="Say A, B, C or D!"
                            )
                        else:
                            res = build_response(
                                "No quiz in progress. Say start the quiz to begin!",
                                attributes,
                                reprompt="Say start the quiz!"
                            )
                    else:
                        res = build_response(
                            "There is nothing to continue right now. "
                            "Say read the document or start the quiz!",
                            attributes,
                            reprompt="Say read the document or start the quiz!"
                        )

                # Quit Intent
                elif intent == "QuitIntent":
                    kid_name = attributes.get("kid_name", "friend")
                    res = build_response(
                        f"Okay {kid_name}! See you next time! "
                        f"Keep being awesome! Bye bye!",
                        end=True
                    )

                else:
                    # FIX: Improved fallback — try multiple ways to extract A/B/C/D
                    kid_name = attributes.get("kid_name", "friend")
                    letter_guess = None

                    # 1. Check all slot values
                    for slot_data in slots.values():
                        val = slot_data.get("value", "")
                        cleaned = clean_answer(val)
                        if cleaned in ["A", "B", "C", "D"]:
                            letter_guess = cleaned
                            break

                    # 2. Check intent name itself (e.g. Alexa mapped "A" as intent name)
                    if not letter_guess:
                        try:
                            raw_value = body["request"]["intent"].get("name", "").upper().strip()
                            if raw_value in ["A", "B", "C", "D"]:
                                letter_guess = raw_value
                        except Exception:
                            pass

                    # 3. FIX: Check the raw user input transcript if available
                    if not letter_guess:
                        try:
                            transcript = body["request"].get("intent", {}).get(
                                "slots", {})
                            for slot_data in transcript.values():
                                spoken = slot_data.get("value", "")
                                cleaned = clean_answer(spoken)
                                if cleaned in ["A", "B", "C", "D"]:
                                    letter_guess = cleaned
                                    break
                        except Exception:
                            pass

                    if letter_guess and attributes.get("questions") and attributes.get("mode") == "quiz":
                        questions = attributes.get("questions")
                        index = attributes.get("index", 0)
                        question = questions[index]
                        user_answer = letter_guess
                        correct_answer = question["answer"].upper()

                        user_answers = attributes.get("user_answers", [])
                        user_answers.append(user_answer)
                        attributes["user_answers"] = user_answers

                        if user_answer == correct_answer:
                            attributes["score"] = attributes.get("score", 0) + 1
                            feedbacks = [
                                "Boom! That is correct! You are on fire!",
                                "Yes yes yes! Amazing answer!",
                                "Correct! You are so smart!",
                                "Nailed it! Keep going superstar!",
                                "Woohoo! That is right!"
                            ]
                            feedback = random.choice(feedbacks)
                        else:
                            correct_text = question["options"][correct_answer]
                            feedback = (
                                f"Oops! Not quite! "
                                f"The correct answer was {correct_answer}: {correct_text}. "
                                f"Do not worry, you will get the next one!"
                            )

                        next_index = index + 1

                        if next_index >= len(questions):
                            score = attributes.get("score", 0)
                            kid_name = attributes.get("kid_name", "friend")
                            kid_id = attributes.get("kid_id")
                            session_id = attributes.get("session_id")

                            closing = safe_finish_quiz(
                                kid_name, kid_id, session_id,
                                questions, user_answers, score, feedback
                            )
                            res = build_response(closing, end=True)
                        else:
                            attributes["index"] = next_index
                            speech = ask_question(questions, next_index, prefix=feedback)
                            res = build_response(
                                speech, attributes,
                                reprompt="Say A, B, C or D!"
                            )
                    else:
                        res = build_response(
                            "Hmm I did not get that! "
                            "You can say start the quiz, read the document, "
                            "continue, repeat, or what is my score!",
                            attributes,
                            reprompt="What would you like to do?"
                        )

            elif req_type == "SessionEndedRequest":
                res = build_response("Goodbye!", end=True)

            else:
                res = build_response("Something went wrong!", end=True)

        except Exception as e:
            res = build_response(
                f"Oops! A critical error happened: {str(e)}",
                end=True
            )

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(res).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(
            {"status": "Alexa endpoint is live!"}
        ).encode())
