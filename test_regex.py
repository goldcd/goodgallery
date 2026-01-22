import re

def test_pattern():
    tags = '* man,* plant,* skull,* bone,* skeleton,* glasses,* hat,* beard,* smiling,* laughing,* sitting,* glass'
    term = "laughing"
    
    # OLD pattern
    escaped_term = re.escape(term.lower())
    old_pattern = fr"(^|\s*,\s*){escaped_term}(\s*,\s*|$)"
    print(f"Old Pattern: {old_pattern}")
    print(f"Match Old: {bool(re.search(old_pattern, tags, re.IGNORECASE))}")
    
    # NEW pattern attempt 1
    # Allow whitespace and optional bullets (* or -) bits before the term
    # But be careful not to match "notlaughing"
    # So we want:
    # boundary is comma or start
    # then optional whitespace
    # then optional (* or -)
    # then optional whitespace
    # then TERM
    # then optional whitespace
    # then boundary
    
    new_pattern = fr"(?:^|,)\s*(?:[\*\-\s]*){escaped_term}(?:[\*\-\s]*)(?:,|$)"
    print(f"New Pattern 2: {new_pattern}")
    print(f"Match New 2: {bool(re.search(new_pattern, tags, re.IGNORECASE))}")
    
    # Test with other messy formats
    cases = [
        ("laughing", True),
        ("* laughing", True),
        (" laughing ", True),
        ("- laughing", True),
        ("man, laughing, dog", True),
        ("man,* laughing, dog", True),
        ("notlaughing", False),
        ("laughingstock", False),
        ("*laughing*", True), # Maybe?
        ("* laughing *", True)
    ]
    
    print("\nTest Cases:")
    for txt, expected in cases:
        m = bool(re.search(new_pattern, txt, re.IGNORECASE))
        print(f"'{txt}': {m} (Expected: {expected}) -> {'OK' if m == expected else 'FAIL'}")

if __name__ == '__main__':
    test_pattern()
