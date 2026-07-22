import re
print(re.compile(".*german.*", re.IGNORECASE).match("My German Deck") is not None)
try:
    re.compile("*german*")
except Exception as e:
    print("Error:", e)
