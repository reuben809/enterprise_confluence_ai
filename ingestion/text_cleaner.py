def chunk_text(text, size=800, overlap=100):
    words=text.split(); i=0
    while i<len(words):
        yield " ".join(words[i:i+size])
        i+=size-overlap
