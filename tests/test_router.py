"""Router and local-answer cases (ported from the original offline suites). Dates are fixed so
holiday answers don't drift."""
import datetime

import pytest

from core.router import local_answer, route

TODAY = datetime.date(2026, 11, 12)

ROUTE_CASES = {
 "definition": ["define ubiquitous", "what's the definition of plant matter", "definition for serendipity",
   "what does ubiquitous mean", "what is the meaning of the word ephemeral", "whats the meaning of gaslighting",
   "can you define photosynthesis for me", "what does the term net zero mean", "what does rizz mean",
   "What does ephemeral mean?", "Define the word quixotic.", "What's the meaning of the word sonder?"],
 "synonym": ["what's another word for happy", "give me a synonym for big", "synonyms of angry",
   "what's a word that means very tired", "different word for important"],
 "drugs": ["what is the maximum dose of tylenol in a day", "how much ibuprofen can I take", "can I take advil with tylenol",
   "side effects of amoxicillin", "is it safe to take benadryl while pregnant", "how often can I take aleve",
   "can I mix nyquil and alcohol", "how many melatonin can a kid have", "does prednisone interact with ibuprofen",
   "what's the dosage of zyrtec for kids", "can i give my kid motrin and tylenol together",
   " What's the max dose of Tylenol?", "How much Benadryl can I give my kid?", "Is it okay to take ibuprofen and Tylenol together?",
   "Can I drink alcohol with amoxicillin?", "how many Advil can I take at once"],
 "health": ["what are the symptoms of strep throat", "what causes migraines", "is the flu contagious",
   "how long does a cold sore last", "how to get rid of a headache", "signs of a concussion",
   "treatment for pink eye", "how long is covid contagious", "what causes high blood pressure", "remedies for a sinus infection",
   "What are the signs of dehydration?", "How long does the flu last?", "What causes kidney stones?"],
 "pets": ["can dogs eat grapes", "is chocolate toxic to cats", "can my dog have peanut butter", "are tulips poisonous to cats",
   "is it safe for dogs to eat bananas", "can cats drink milk", "is garlic bad for dogs", "can puppies eat cheese",
   "Can my cat eat tuna?", "Is xylitol poisonous to dogs?", "Are grapes OK for dogs?", "Can dogs have watermelon?"],
 "food_safety": ["what temperature should chicken be cooked to", "what temp is pork safe to eat", "how long are leftovers good in the fridge",
   "how long can cooked rice sit out", "is it safe to eat pink pork", "how long does ground beef last in the freezer",
   "how do I thaw a turkey", "what internal temp is a burger done", "how long do eggs last in the fridge",
   "What temperature do you cook pork to?", "How long is chicken good in the fridge?",
   "Is it safe to eat raw cookie dough after it's expired?"],
 "garden": ["when should I plant peppers", "how often should I water tomato plants", "how deep do you plant garlic",
   "why are my pepper plants turning yellow", "when do you prune roses", "how far apart should I plant cucumbers",
   "when to transplant tomato seedlings", "how much sun do peppers need",
   "When do I plant tomatoes in Minnesota?", "How often do you water succulents?"],
 "movies": ["who plays walter white", "who starred in the matrix", "how many seasons of the office are there",
   "when did the first iron man come out", "who voiced woody in toy story", "cast of stranger things",
   "what year did jurassic park come out", "who directed jaws",
   "Who plays Wednesday Addams?", "When did Toy Story come out?", "How many episodes are in Breaking Bad?", "Who sang Bohemian Rhapsody"],
 "people_history": ["who was abraham lincoln", "who is Taylor Swift", "when was george washington born",
   "who invented the light bulb", "when did world war 2 end", "who was the first person on the moon",
   "when was the eiffel tower built", "who won the super bowl in 2020", "how old is Tom Hanks", "where was elvis born",
   "Who was Nikola Tesla?", "When did the Titanic sink?"],
}
NO_ROUTE = [
 "how tall is mount everest in feet", "what causes thunder", "what causes the tides", "how many dogs are in the united states",
 "how many calories are in a hot dog", "can I eat a hot dog", "what is a black hole", "who is at the door",
 "who is home", "how long is the drive to chicago", "how long is the movie dune", "what time does home depot close",
 "how far is the moon", "what is the capital of australia", "why is the sky blue", "how many ounces are in a cup of coffee shop size",
 "how do airplanes fly", "what is the population of texas", "how much does a tesla cost", "what's the weather like in paris",
 "is it safe to drive in snow", "how long do cats live", "how big do great danes get", "what temperature does water boil",
 "how hot is the sun", "who is the best basketball player", "what is the fastest car", "how do I reset my router",
 "what's the meaning of life", "how many people live in canada", "what is the stock price of apple",
 "What's the weather tomorrow?", "Who's at the front door?", "Can the dog go outside?", "Is the cat food low?",
 "How long is the dishwasher cycle?", "What's the temperature inside?", "What temperature is it in the garage?",
 "How long does it take to cook rice?", "When does the pool close?", "Are the dogs inside?",
 "How long will the pizza take?", "What does the fox say?",
 "How do I make chicken alfredo?", "What do dogs dream about?", "Why do cats purr?",
]
LOCAL_CASES = [
 ("how do you spell necessary", "N, E, C, E, S, S, A, R, Y"), ("spell rhythm", "R, H, Y, T, H, M"),
 ("how is accommodate spelled", "A, C, C"), ("can you spell Emma", "E, M, M, A"),
 ("what's 18 times 24", "432"), ("what is 15 percent of 80", "12"), ("how much is 100 divided by 8", "12.5"),
 ("what's 7 plus 6", "13"), ("what is 1,250 minus 375", "875"), ("what's the square root of 144", "12"),
 ("what is 12 squared", "144"), ("what's twenty times four", "80"), ("what is 3.5 times 2", "7"),
 ("how many ounces are in a cup", "8 fluid ounces"), ("how many tablespoons in a cup", "16"),
 ("how many teaspoons in a tablespoon", "3"), ("how many cups in a gallon", "16"), ("how many ounces in a pound", "16"),
 ("how many grams in a pound", "453.59"), ("convert 5 miles to kilometers", "8.05"), ("how many feet in a mile", "5,280"),
 ("what's 350 degrees fahrenheit in celsius", "176.7"), ("how many ml in a teaspoon", "4.93"),
 ("how many cups in 2 quarts", "8"), ("10 kilograms in pounds", "22.05"), ("how many inches in a foot", "12"),
 ("how many days until christmas", "days away"), ("how many days till halloween", "days away"),
 ("how many days until thanksgiving", "Thursday, November 26"), ("how many weeks until christmas", "weeks away"),
 ("what day is the 4th of july", "July 4"), ("what day of the week is christmas", "December 25"),
 ("how many days since january 1st", "since"), ("how many days until march 15th", "March 15"),
 ("how long until new year's", "January 1"), ("what day is easter", "March 28"),
 (" What's 18 times 24?", "432"), ("What is 15% of 80?", "12"), ("How many ounces are in a cup?", "8 fluid"),
 ("How many days until Christmas?", "Christmas is"), ("How do you spell 'definitely'?", "D, E, F"),
 ("Please, what's 9 times 7?", "63"), ("What's 72 degrees Fahrenheit in Celsius?", "22.2"),
 ("How many tablespoons are in a quarter cup?", "4"), ("What day is Thanksgiving this year?", "November 26"),
 ("How many sleeps until Christmas?", "Christmas is"),
]
NO_LOCAL = [
 "what is a spell", "how do you cast a spell", "spell check", "how many times has the eagles won the super bowl",
 "what's the times table for 7", "how many cups of coffee is too much", "how many feet tall is everest",
 "how many miles to chicago", "how many days in a year", "what day is it", "what day is it today",
 "what's the date", "how many weeks in a year", "how many ounces of water should I drink a day",
 "what is 5 guys", "what's 2 broke girls about", "how many days does it take to get to mars",
 "how many pounds is a gallon of water", "how long until the tesla is charged", "how much is a pound of beef",
 "who is number 23 on the bulls", "how many cups in a gallon of milk at costco cost",
 "How many days till my birthday?",
 "What time is it?", "What's today's date?", "How many days are in February?", "Spell it out for me.",
 "How many times did I open the garage today?", "What's 5 Guys hours?", "How much is gas?",
 "How many cups of flour in a pound?", "What's two plus two equals four song?",
]


@pytest.mark.parametrize("want,q", [(w, q) for w, qs in ROUTE_CASES.items() for q in qs])
def test_route(want, q):
    assert route(q)[0] == want


@pytest.mark.parametrize("q", NO_ROUTE)
def test_no_route(q):
    assert route(q)[0] is None


@pytest.mark.parametrize("q,expect", LOCAL_CASES)
def test_local(q, expect):
    a = local_answer(q, TODAY)
    assert a and expect.lower() in a.lower(), a


@pytest.mark.parametrize("q", NO_LOCAL)
def test_no_local(q):
    assert local_answer(q, TODAY) is None
