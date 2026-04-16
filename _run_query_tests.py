from app.assistant import fix_wine_question_typos
from app.repository import WineRepository
from app.query_engine import (
    default_query_plan,
    filter_wines_heuristic,
    filter_wines_with_plan,
    question_is_wine_related,
)

r = WineRepository()
r.load()

q0 = fix_wine_question_typos("How about like just some wise around 40?")
assert "wines" in q0 and "wise" not in q0, q0
p0 = default_query_plan(q0, r)
df0 = filter_wines_with_plan(p0, r)
assert p0["sort_by"] == "price_near" and p0["near_price"] == 40.0
assert len(df0) >= 3
assert float(df0["Retail"].min()) >= 32 and float(df0["Retail"].max()) <= 48

q1 = "Which are the best-rated wines under $50?"
p1 = default_query_plan(q1, r)
df1 = filter_wines_with_plan(p1, r)
assert p1["max_price"] == 50 and p1["sort_by"] == "rating_desc"
assert float(df1["Retail"].max()) <= 50.01

df2 = filter_wines_heuristic("What do you have from Burgundy?", r)
assert len(df2) >= 3
assert (df2["region_normalized"] == "burgundy").all()

p3 = default_query_plan("What's the most expensive bottle you have?", r)
df3 = filter_wines_with_plan(p3, r)
assert p3["sort_by"] == "price_desc"
assert float(df3["Retail"].iloc[0]) >= float(df3["Retail"].iloc[-1])

q4 = "Which bottles would make a good housewarming gift?"
assert question_is_wine_related(q4, r)
p4 = default_query_plan(q4, r)
df4 = filter_wines_with_plan(p4, r)
assert len(df4) >= 3

print("query pipeline tests: OK")
