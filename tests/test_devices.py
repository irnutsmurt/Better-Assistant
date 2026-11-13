

def test_say_lights_on_and_tv():
    from core.devices import say_lights_on, say_tv
    assert say_lights_on([]) == "All the lights are off."
    assert say_lights_on([("Living Room", ["Living room lamps", "Desk lamp"]), ("Porch", ["Porch light"])]) == \
        "3 lights are on: Living room lamps and Desk lamp in the living room; Porch light in the porch."
    assert say_lights_on([("Kitchen", ["Ceiling"])], "Kitchen") == "1 light is on in the kitchen: Ceiling."
    assert say_lights_on([], "Kitchen") == "All the lights in the kitchen are off."
    # the living room TV as five media players: only Cast knows the title
    five = [{"state": "playing", "title": "The Cartel Explained", "artist": "Cappy Army", "app": "YouTube"},
            {"state": "on", "app": "com.google.android.youtube.tv"},
            {"state": "idle"}, {"state": "idle", "app": "music_assistant", "source": "Music Assistant Queue"},
            {"state": "on", "source": "AirPlay"}]
    assert say_tv("living room TV", five) == \
        "The living room TV is playing The Cartel Explained by Cappy Army on YouTube."
    assert say_tv("living room TV", [{"state": "on", "app": "com.google.android.youtube.tv"}, {"state": "idle"}]) == \
        "There's nothing playing on the living room TV. YouTube is open."
    assert say_tv("living room TV", [{"state": "idle"}]) == "There's nothing playing on the living room TV."
    assert say_tv("living room TV", [{"state": "off"}, {"state": "unavailable"}]) == "The living room TV is off."
    assert say_tv("living room TV", [{"state": "paused", "title": "Bluey", "app": "Disney+"}]) == \
        "The living room TV has Bluey paused on Disney+."
