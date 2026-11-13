

def test_say_lights_on_and_tv():
    from core.devices import say_lights_on, say_tv
    assert say_lights_on([]) == "All the lights are off."
    assert say_lights_on([("Living Room", ["Living room lamps", "Desk lamp"]), ("Porch", ["Porch light"])]) == \
        "3 lights are on: Living room lamps and Desk lamp in the living room; Porch light in the porch."
    assert say_lights_on([("Kitchen", ["Ceiling"])], "Kitchen") == "1 light is on in the kitchen: Ceiling."
    assert say_lights_on([], "Kitchen") == "All the lights in the kitchen are off."
    assert say_tv("Living room TV", "playing", "Bluey", None, "Disney+", None) == \
        "The Living room TV is playing Bluey on Disney+."
    assert say_tv("Living room TV", "on", None, None, None, "HDMI 2") == "The Living room TV is on HDMI 2."
    assert say_tv("Living room TV", "off", None, None, None, None) == "The Living room TV is off."
