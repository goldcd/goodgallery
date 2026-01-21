import re

# Test the REGEXP logic
def regexp(pattern, string):
    """Case-insensitive REGEXP for SQLite"""
    if string is None:
        return False
    return re.search(pattern, string, re.IGNORECASE) is not None

# Test tags
test_tags = [
    ("man,woman,smiling", "man", "woman"),  # Should match: has both
    ("man,shirt", "man", "woman"),  # Should NOT match: missing woman
    ("woman,dress", "man", "woman"),  # Should NOT match: missing man  
    ("human,woman", "man", "woman"),  # Should NOT match: 'man' in 'human'
]

for tags, term1, term2 in test_tags:
    # Build patterns like the code does
    escaped1 = re.escape(term1.lower())
    escaped2 = re.escape(term2.lower())
    pattern1 = fr"(^|[^a-zA-Z0-9]){escaped1}([^a-zA-Z0-9]|$)"
    pattern2 = fr"(^|[^a-zA-Z0-9]){escaped2}([^a-zA-Z0-9]|$)"
    
    match1 = regexp(pattern1, tags)
    match2 = regexp(pattern2, tags)
    both_match = match1 and match2
    
    print(f"Tags: {tags}")
    print(f"  man match: {match1}, woman match: {match2}, both: {both_match}")
    print()
