import hashlib
def question_hash(text):
    return hashlib.md5(text.encode()).hexdigest()
