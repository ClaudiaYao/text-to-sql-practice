"""Hand-written Sakila semantics the schema alone cannot convey. Edit here to fix systematic mistakes."""

SAKILA_NOTES = """\
- Revenue / sales / "paid" = SUM(payment.amount). film.rental_rate is the listed price per rental and
  film.replacement_cost is the cost to replace a lost copy — neither is revenue.
- A rental is for one physical copy: rental.inventory_id -> inventory (copy, store_id) -> film.
  To link rentals/payments to films or categories go rental -> inventory -> film [-> film_category -> category].
  payment.rental_id links a payment to its rental.
- Locations: customer, staff and store each have address_id -> address -> city -> country.
- Cast and genres are many-to-many: film_actor (film<->actor) and film_category (film<->category).
  A film has exactly one category row in standard Sakila, but always join through film_category.
- rental.return_date IS NULL means the rental is not returned yet. Rental duration = return_date - rental_date.
- Customer status: the integer customer.active (1 = active, 0 = inactive) is the real flag. customer.activebool
  is TRUE for every customer in this dataset, so never use it to find inactive customers. Do not filter on
  either unless the user asks about active/inactive customers.
- Store attribution: revenue/payments belong to the store of the staff member who processed them
  (payment.staff_id -> staff.store_id); a rental's physical copy belongs to inventory.store_id. These give
  slightly different per-store totals, so follow the wording ("processed by", "copies in a store's inventory").
- A rental can have more than one payment row (a few do), so sum payments for revenue; never count payments
  as rentals.
- Names and titles are stored in UPPERCASE (e.g. 'MARY', 'ACADEMY DINOSAUR'); category names are capitalised
  ('Action'). Match text with ILIKE / LOWER() so case never matters.
- Names are not unique (two actors/customers can share a name): group and join on ids, then show names.
- film.length is minutes; film.rating is an enum (see ENUM VALUES); special_features is a text array
  (use 'Trailers' = ANY(special_features)).
- "Rating" always means the MPAA rating film.rating (G, PG, ...), never category.name; "category" / "genre"
  means category.name. They are different attributes, and film.rating needs no join.
- The data is historical, not current: for relative phrases ("last month", "recent", "this year") anchor on
  MAX(<date column>) of the relevant table rather than CURRENT_DATE, unless the user gives explicit dates.
- Prefer base tables (listed in the schema) over the convenience views.
"""
