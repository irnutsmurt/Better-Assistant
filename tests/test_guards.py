

def test_house_state_questions_never_go_to_the_web():
    from core.guards import looks_like_command
    for q in ("what lights are on the house right now", "is the garage door open",
              "what's playing on the tv", "are the doors locked"):
        assert looks_like_command(q, []), q
    for q in ("how far away is the moon", "why do cats purr", "who won the world series in 1998"):
        assert not looks_like_command(q, []), q
