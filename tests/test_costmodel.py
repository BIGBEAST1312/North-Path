"""Tests. Run with:  python -m unittest discover -s tests -v

They cover the parts where a bug would produce a plausible-looking wrong number,
which is the failure mode that matters for this project.
"""
import pathlib
import unittest
from datetime import date

from costmodel import (
    Range,
    Student,
    affordability,
    calibrate,
    estimate_cost,
    load_all,
    load_degrees,
    load_outlook,
    load_programs,
    load_weights,
    rank,
)
from costmodel.calibrate import report_markdown
from costmodel.match import (
    admission_fit,
    admission_label,
    cost_fit,
    degree_fit,
    preference_fit,
    safety_fit,
    token_similarity,
)


class TestRange(unittest.TestCase):
    def test_rejects_inverted(self):
        with self.assertRaises(ValueError):
            Range(low=900, high=400)

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            Range(low=-10, high=100)

    def test_mid_and_contains(self):
        r = Range(low=600, high=900)
        self.assertEqual(r.mid, 750)
        self.assertTrue(r.contains(600))
        self.assertTrue(r.contains(900))
        self.assertFalse(r.contains(901))

    def test_undated_counts_as_stale(self):
        self.assertTrue(Range(low=1, high=2).is_stale(6))

    def test_fresh_figure_not_stale(self):
        r = Range(low=1, high=2, as_of="2026-09-01", verified=True)
        self.assertFalse(r.is_stale(6, today=date(2026, 10, 1)))
        self.assertTrue(r.is_stale(6, today=date(2027, 6, 1)))

    def test_scaled_keeps_provenance(self):
        r = Range(low=100, high=200, n=12, source_url="http://x", as_of="2026-09-01", verified=True)
        s = r.scaled(12)
        self.assertEqual((s.low, s.high), (1200, 2400))
        self.assertEqual(s.n, 12)
        self.assertTrue(s.verified)


class TestStudent(unittest.TestCase):
    def test_validates_inputs(self):
        with self.assertRaises(ValueError):
            Student(average_percent=140, tuition_budget=1000)
        with self.assertRaises(ValueError):
            Student(average_percent=80, tuition_budget=-1)
        with self.assertRaises(ValueError):
            Student(average_percent=80, tuition_budget=1000, housing_type="castle")


class TestEstimate(unittest.TestCase):
    def setUp(self):
        self.cities, self.programs, self.expiry = load_all()
        self.by_id = {p.id: p for p in self.programs}

    def test_total_is_tuition_plus_living(self):
        student = Student(average_percent=80, tuition_budget=30000, months_per_year=12)
        prog = self.by_id["usask-cs"]
        est = estimate_cost(prog, self.cities["Saskatoon"], student, self.expiry)
        self.assertAlmostEqual(est.total_low, est.tuition.value + est.living_low)
        self.assertLess(est.total_low, est.total_high)

    def test_housing_ladder_is_ordered(self):
        prog = self.by_id["usask-cs"]
        city = self.cities["Saskatoon"]
        shared = estimate_cost(prog, city, Student(average_percent=80, tuition_budget=0, housing_type="private_room"), self.expiry)
        solo = estimate_cost(prog, city, Student(average_percent=80, tuition_budget=0, housing_type="studio"), self.expiry)
        self.assertLess(shared.total_low, solo.total_low)

    def test_fewer_months_costs_less(self):
        prog = self.by_id["usask-cs"]
        city = self.cities["Saskatoon"]
        eight = estimate_cost(prog, city, Student(average_percent=80, tuition_budget=0, months_per_year=8), self.expiry)
        twelve = estimate_cost(prog, city, Student(average_percent=80, tuition_budget=0, months_per_year=12), self.expiry)
        self.assertLess(eight.living_low, twelve.living_low)

    def test_domestic_cheaper_than_international(self):
        prog = self.by_id["usask-cs"]
        city = self.cities["Saskatoon"]
        intl = estimate_cost(prog, city, Student(average_percent=80, tuition_budget=0, status="international"), self.expiry)
        dom = estimate_cost(prog, city, Student(average_percent=80, tuition_budget=0, status="domestic"), self.expiry)
        self.assertLess(dom.total_low, intl.total_low)

    def test_placeholder_data_reports_unverified(self):
        prog = self.by_id["usask-cs"]
        est = estimate_cost(prog, self.cities["Saskatoon"], Student(average_percent=80, tuition_budget=0), self.expiry)
        self.assertTrue(est.unverified_fields)
        self.assertEqual(est.confidence, "unverified")


class TestAffordability(unittest.TestCase):
    def setUp(self):
        self.cities, self.programs, self.expiry = load_all()
        self.prog = {p.id: p for p in self.programs}["usask-cs"]

    def _est(self, budget):
        student = Student(average_percent=80, tuition_budget=budget)
        return estimate_cost(self.prog, self.cities["Saskatoon"], student, self.expiry)

    def test_within_tuition_budget(self):
        est = self._est(500000)
        result = affordability(est, 500000)
        self.assertEqual(result["verdict"], "within tuition budget")
        self.assertEqual(result["headroom"], 500000 - est.tuition.value)

    def test_over_tuition_budget(self):
        est = self._est(1000)
        self.assertEqual(affordability(est, 1000)["verdict"], "over tuition budget")

    def test_living_costs_reported_not_budgeted(self):
        # A budget exactly equal to tuition is within budget, even though living
        # costs push the real total well above it.
        est = self._est(0)
        result = affordability(est, est.tuition.value)
        self.assertEqual(result["verdict"], "within tuition budget")
        self.assertGreater(result["living_low"], 0)


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.cities, self.programs, self.expiry = load_all()
        self.by_id = {p.id: p for p in self.programs}

    def test_admission_fit_monotonic(self):
        prog = self.by_id["usask-cs"]
        low = admission_fit(Student(average_percent=60, tuition_budget=0), prog)
        high = admission_fit(Student(average_percent=95, tuition_budget=0), prog)
        self.assertLess(low, high)
        self.assertTrue(0 <= low <= 1 and 0 <= high <= 1)

    def test_labels(self):
        prog = self.by_id["usask-cs"]  # cutoff 70
        self.assertEqual(admission_label(Student(average_percent=95, tuition_budget=0), prog), "safety")
        self.assertEqual(admission_label(Student(average_percent=72, tuition_budget=0), prog), "match")
        self.assertEqual(admission_label(Student(average_percent=60, tuition_budget=0), prog), "reach")

    def test_cost_fit_bounds(self):
        prog = self.by_id["usask-cs"]
        est = estimate_cost(prog, self.cities["Saskatoon"], Student(average_percent=80, tuition_budget=0), self.expiry)
        self.assertAlmostEqual(cost_fit(est, 10_000_000), 1.0, places=2)
        self.assertEqual(cost_fit(est, est.tuition.value), 0.75)
        self.assertEqual(cost_fit(est, 1000), 0.0)
        self.assertEqual(cost_fit(est, 0), 0.0)

    def test_similarity(self):
        self.assertEqual(token_similarity("", "anything"), 0.5)
        strong = token_similarity("artificial intelligence", "streams in artificial intelligence")
        weak = token_similarity("marine biology", "streams in artificial intelligence")
        self.assertGreater(strong, weak)

    def test_rank_orders_by_score_and_respects_budget(self):
        student = Student(average_percent=78, tuition_budget=25000, wants_coop=True, preferred_city_size="small")
        results = rank(student, self.programs, self.cities, load_weights(), self.expiry)
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # An expensive out-of-reach program should not top the list for this student.
        self.assertNotEqual(results[0]["program"].id, "utoronto-cs")

    def test_rank_limit(self):
        student = Student(average_percent=78, tuition_budget=25000)
        self.assertEqual(len(rank(student, self.programs, self.cities, limit=2)), 2)


class TestCalibration(unittest.TestCase):
    def setUp(self):
        self.cities, _, _ = load_all()

    def test_empty_reports_no_coverage(self):
        result = calibrate(self.cities, [])
        self.assertIsNone(result["coverage"])
        self.assertIn("uncalibrated", report_markdown(result))

    def test_coverage_counts_hits(self):
        city = self.cities["Saskatoon"]
        rent = city.rent("private_room", "near")
        rows = [
            {"city": "Saskatoon", "housing_type": "private_room", "proximity": "near", "rent": rent.mid,
             "food": None, "transit": None, "phone_internet": None, "other": None},
            {"city": "Saskatoon", "housing_type": "private_room", "proximity": "near", "rent": rent.high + 5000,
             "food": None, "transit": None, "phone_internet": None, "other": None},
        ]
        result = calibrate(self.cities, rows)
        self.assertEqual(result["per_category"]["rent"]["n"], 2)
        self.assertAlmostEqual(result["per_category"]["rent"]["coverage"], 0.5)

    def test_unknown_city_is_reported(self):
        rows = [{"city": "Atlantis", "housing_type": "private_room", "proximity": "near", "rent": 900,
                 "food": None, "transit": None, "phone_internet": None, "other": None}]
        self.assertEqual(calibrate(self.cities, rows)["unknown_cities"], ["Atlantis"])


if __name__ == "__main__":
    unittest.main()


class TestHousingAndSafety(unittest.TestCase):
    """The three options added after the first build: housing type, distance
    from campus, and whether crime figures count."""

    def setUp(self):
        self.cities, self.programs, self.expiry = load_all()
        self.prog = {p.id: p for p in self.programs}["usask-cs"]
        self.city = self.cities["Saskatoon"]

    def _total(self, **kw):
        student = Student(average_percent=80, tuition_budget=0, **kw)
        return estimate_cost(self.prog, self.city, student, self.expiry).total_low

    def test_housing_types_are_ordered(self):
        shared = self._total(housing_type="shared_room")
        private = self._total(housing_type="private_room")
        studio = self._total(housing_type="studio")
        self.assertLess(shared, private)
        self.assertLess(private, studio)

    def test_distance_changes_transit_but_not_rent(self):
        # The rent source is one city-wide average with no campus-distance split,
        # so a discount for living further out would be invented.
        near_rent = self.city.rent("private_room", "near")
        far_rent = self.city.rent("private_room", "far")
        self.assertEqual((far_rent.low, far_rent.high), (near_rent.low, near_rent.high))
        self.assertGreater(self.city.transit("far").low, self.city.transit("near").low)

    def test_unknown_housing_or_proximity_rejected(self):
        with self.assertRaises(ValueError):
            self.city.rent("penthouse", "near")
        with self.assertRaises(ValueError):
            self.city.transit("nearby")

    def _with_safety(self, csi):
        """Build a copy of the city carrying a crime figure.

        The shipped data has none on purpose — crime numbers about real cities
        are not something to invent — so the scoring is tested against a
        constructed one.
        """
        from costmodel.schema import City as _City, Figure as _Figure, Safety as _Safety
        return _City(
            city=self.city.city, province=self.city.province, size_band=self.city.size_band,
            costs=self.city.costs,
            safety=_Safety(crime_severity_index=_Figure(value=csi, verified=True)),
        )

    def test_safety_descriptor_and_fit(self):
        calm, rough = self._with_safety(55), self._with_safety(140)
        self.assertIn("average", calm.safety.descriptor())
        self.assertGreater(safety_fit(calm), safety_fit(rough))
        self.assertTrue(0 <= safety_fit(rough) <= 1)

    def test_crime_flag_changes_preference_score(self):
        rough = self._with_safety(140)  # constructed, so the test doesn't depend on one city
        off = Student(average_percent=80, tuition_budget=40000, crime_matters=False)
        on = Student(average_percent=80, tuition_budget=40000, crime_matters=True)
        self.assertNotEqual(
            preference_fit(off, self.prog, rough),
            preference_fit(on, self.prog, rough),
        )

    def test_shipped_cities_carry_real_crime_data_or_none(self):
        with_csi = [c for c in self.cities.values() if c.safety]
        self.assertEqual(len(with_csi), 15)
        for c in with_csi:
            self.assertIn("Statistics Canada", c.safety.crime_severity_index.source)
            self.assertGreater(c.safety.crime_severity_index.value, 0)
        # Cities absent from the published table keep no figure rather than a guess.
        self.assertIsNone(self.cities["Victoria"].safety)

    def test_crime_flag_off_is_ignored_entirely(self):
        student = Student(average_percent=80, tuition_budget=40000, crime_matters=False)
        result = rank(student, self.programs, self.cities, limit=1)[0]
        self.assertFalse(result["safety_considered"])

    def test_safety_fit_none_without_data(self):
        self.assertIsNone(safety_fit(self.cities["Victoria"]))

    def test_real_csi_orders_cities(self):
        # Winnipeg 130.93 vs Ottawa 55.75 in the 2024 table.
        self.assertLess(safety_fit(self.cities["Winnipeg"]), safety_fit(self.cities["Ottawa"]))


class TestDegrees(unittest.TestCase):
    """Ranking is driven by the degree the student picks."""

    def test_catalogue_has_41_options_with_one_pathway(self):
        degrees = load_degrees()
        self.assertEqual(len(degrees), 41)
        self.assertEqual([d.id for d in degrees.values() if d.kind == "pathway"], ["premed"])

    def test_every_degree_loads_the_schools_that_offer_it(self):
        for d in load_degrees().values():
            if d.kind == "degree":
                self.assertLessEqual(len(load_programs(d.id)), 25, d.id)
                self.assertGreater(len(load_programs(d.id)), 0, d.id)

    def test_schools_confirmed_not_to_offer_a_degree_are_excluded(self):
        # Waterloo, SFU, Guelph, Concordia and UQAM have no undergraduate nursing degree.
        ids = {p.university_id for p in load_programs("nursing")}
        for uid in ("uwaterloo", "sfu", "uguelph", "concordia", "uqam"):
            self.assertNotIn(uid, ids)
        self.assertEqual(len(ids), 20)

    def test_unknown_degree_rejected(self):
        with self.assertRaises(ValueError):
            load_programs("mbbs")

    def test_not_offered_is_excluded(self):
        import json, shutil, tempfile, pathlib
        src = pathlib.Path(__file__).resolve().parent.parent / "data"
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            for f in src.iterdir():
                shutil.copy(f, tmp / f.name)
            off = json.loads((tmp / "offerings.json").read_text())
            off["offerings"]["usask-architecture"]["offered"] = {"value": False, "verified": True,
                                                                "source_url": "x", "as_of": "2026-09-21"}
            (tmp / "offerings.json").write_text(json.dumps(off))
            ids = {p.id for p in load_programs("architecture", tmp)}
            self.assertNotIn("usask-architecture", ids)
            self.assertEqual(len(ids), 24)

    def test_subject_strength_beats_overall_fallback(self):
        from costmodel.schema import Figure
        from dataclasses import replace
        prog = {p.id: p for p in load_programs("nursing")}["usask-nursing"]
        fallback, basis = degree_fit(prog)
        self.assertEqual(basis, "overall")
        strong = replace(prog, subject_strength=Figure(value=95, verified=True))
        score, basis = degree_fit(strong)
        self.assertEqual(basis, "subject")
        self.assertGreater(score, fallback)

    def test_subject_strength_changes_the_ranking(self):
        from costmodel.schema import Figure
        from dataclasses import replace
        cities, progs, expiry = load_all("nursing")
        student = Student(average_percent=85, tuition_budget=50000)
        before = rank(student, progs, cities, expiry_months=expiry)
        last_id = before[-1]["program"].id
        boosted = [replace(p, subject_strength=Figure(value=100, verified=True)) if p.id == last_id
                   else replace(p, subject_strength=Figure(value=10, verified=True)) for p in progs]
        after = rank(student, boosted, cities, expiry_months=expiry)
        self.assertLess([r["program"].id for r in after].index(last_id), len(after) - 1)

    def test_premed_pathway_ranks_undergrad_routes_one_per_university(self):
        cities, progs, expiry = load_all("premed")
        self.assertEqual({p.degree_id for p in progs}, {"biology", "health-sci", "biochem", "neuro"})
        results = rank(Student(average_percent=88, tuition_budget=50000), progs, cities,
                       expiry_months=expiry, one_per_university=True)
        unis = [r["program"].university_id for r in results]
        self.assertEqual(len(unis), len(set(unis)))
        self.assertIn("MBBS", load_degrees()["premed"].notice)

    def test_outlook_does_not_change_scores(self):
        # Outlook is display-only: scoring never reads it.
        import inspect
        import costmodel.match as m
        self.assertNotIn("outlook", inspect.getsource(m))
        self.assertIn("nursing", load_outlook())


class TestSubjectRankings(unittest.TestCase):
    """THE 2026 subject scores drive degree strength; unlisted schools sit below listed ones."""

    def test_the_scores_loaded(self):
        progs = {p.id: p for p in load_programs("cs")}
        self.assertEqual(progs["utoronto-cs"].subject_strength.value, 87.7)
        self.assertIn("THE World University Rankings 2026", progs["utoronto-cs"].subject_strength.source)
        self.assertIsNone(progs["usask-cs"].subject_strength)  # not in THE's Canadian CS list

    def test_unlisted_school_never_outscores_a_listed_one(self):
        from costmodel.match import unlisted_floors
        for deg in ("cs", "nursing", "business", "mech-eng", "psychology", "education", "physics", "english"):
            progs = load_programs(deg)
            floor = unlisted_floors(progs)[deg]
            listed = [degree_fit(p, 25, floor)[0] for p in progs if p.subject_strength]
            unlisted = [degree_fit(p, 25, floor) for p in progs if not p.subject_strength]
            self.assertTrue(unlisted, deg)
            for score, basis in unlisted:
                self.assertEqual(basis, "unlisted")
                self.assertLess(score, min(listed))

    def test_degree_without_data_still_falls_back_to_overall(self):
        cities, progs, expiry = load_all("biology")
        r = rank(Student(average_percent=85, tuition_budget=60000), progs, cities, expiry_months=expiry)
        self.assertEqual({x["degree_basis"] for x in r}, {"overall"})

    def test_card_names_the_source(self):
        from costmodel.explain import explain
        cities, progs, expiry = load_all("cs")
        r = rank(Student(average_percent=95, tuition_budget=200000), progs, cities, expiry_months=expiry)
        top = next(x for x in r if x["program"].id == "utoronto-cs")
        self.assertIn("87.7/100", explain(top))
        self.assertIn("THE World University Rankings 2026", explain(top))



class TestTuitionBudgetFilter(unittest.TestCase):
    """The budget is tuition only, and it is a hard limit."""

    def setUp(self):
        self.cities, self.progs, self.expiry = load_all("business")

    def _rank(self, budget, **kw):
        return rank(Student(average_percent=85, tuition_budget=budget, **kw),
                    self.progs, self.cities, expiry_months=self.expiry)

    def test_nothing_over_budget_is_returned(self):
        for budget in (25000, 30000, 45000, 70000):
            for r in self._rank(budget):
                self.assertLessEqual(r["estimate"].tuition.value, budget)

    def test_too_low_budget_returns_nothing(self):
        from costmodel import cheapest_tuition
        cheapest = cheapest_tuition(self.progs, "international")
        self.assertEqual(self._rank(cheapest - 1), [])
        self.assertTrue(self._rank(cheapest))

    def test_domestic_status_uses_domestic_tuition(self):
        self.assertEqual(self._rank(12000), [])  # below every international fee
        self.assertTrue(self._rank(12000, status="domestic"))

    def test_budget_does_not_move_unlisted_floor(self):
        # Filtering out expensive listed schools must not lift unlisted ones' degree score.
        low = {r["program"].id: r["components"]["degree_fit"] for r in self._rank(30000)}
        high = {r["program"].id: r["components"]["degree_fit"] for r in self._rank(200000)}
        for pid, v in low.items():
            self.assertAlmostEqual(v, high[pid])

    def test_web_page_shows_no_match_message(self):
        from app import app
        c = app.test_client()
        r = c.post("/", data={"average": "85", "budget": "1000", "status": "international",
                              "housing_type": "private_room", "proximity": "near", "months": "12",
                              "city_size": "", "degree": "business"})
        self.assertIn(b"No universities available for the selected tuition fee budget", r.data)
        self.assertIn(b"lowest tuition for this degree", r.data)

    def test_accented_names_render(self):
        from app import app
        r = app.test_client().post("/", data={"average": "85", "budget": "100000", "status": "international",
                                               "housing_type": "private_room", "proximity": "near",
                                               "months": "12", "city_size": "", "degree": "business"})
        self.assertIn("Université".encode("utf-8"), r.data)
        self.assertNotIn("UniversitÃ".encode("utf-8"), r.data)


class TestCoopStrength(unittest.TestCase):
    def setUp(self):
        self.cities, self.progs, self.expiry = load_all("cs")
        self.by = {p.university_id: p for p in self.progs}

    def test_list_loaded(self):
        from costmodel.match import coop_fit
        self.assertEqual(self.by["uwaterloo"].coop_strength.value, 100)
        self.assertIsNone(self.by["utoronto"].coop_strength is None or None)
        self.assertGreater(coop_fit(self.by["uwaterloo"]), coop_fit(self.by["unb"]))

    def test_unlisted_school_sits_at_the_baseline_not_zero(self):
        from costmodel.match import coop_fit
        from dataclasses import replace
        unlisted = replace(self.by["uwaterloo"], coop_strength=None)
        self.assertEqual(coop_fit(unlisted), 0.6)

    def test_no_coop_scores_zero(self):
        from costmodel.match import coop_fit
        from dataclasses import replace
        from costmodel.schema import Flag
        self.assertEqual(coop_fit(replace(self.by["uwaterloo"], coop=Flag(value=False))), 0.0)

    def test_coop_only_counts_when_asked_for(self):
        from costmodel.match import preference_fit
        city = self.cities["Waterloo"]
        off = Student(average_percent=85, tuition_budget=80000, wants_coop=False)
        on = Student(average_percent=85, tuition_budget=80000, wants_coop=True)
        self.assertNotEqual(preference_fit(off, self.by["uwaterloo"], city),
                            preference_fit(on, self.by["uwaterloo"], city))


class TestRentData(unittest.TestCase):
    """Rent comes from a supplied 1-BR table; anything not in it is labelled."""

    def setUp(self):
        self.cities, _, _ = load_all()

    def test_studio_matches_the_published_average(self):
        # Toronto 1-BR average $2,400 -> -15% / +20%
        st = self.cities["Toronto"].rent("studio", "near")
        self.assertEqual((st.low, st.high), (2040, 2880))
        self.assertIn("Toronto 1-BR average", st.source)

    def test_room_rents_are_labelled_as_derived(self):
        city = self.cities["Toronto"]
        for ht in ("shared_room", "private_room"):
            self.assertTrue(city.rent(ht, "near").source.startswith("Derived"))
        self.assertFalse(city.rent("studio", "near").source.startswith("Derived"))

    def test_housing_ladder_still_ordered(self):
        city = self.cities["Vancouver"]
        self.assertLess(city.rent("shared_room", "near").low, city.rent("private_room", "near").low)
        self.assertLess(city.rent("private_room", "near").low, city.rent("studio", "near").low)

    def test_provincial_fallback_says_so(self):
        self.assertIn("provincial 1-BR average", self.cities["Guelph"].rent("studio", "near").source)
        self.assertIn("Kitchener", self.cities["Waterloo"].rent("studio", "near").source)

    def test_derived_rent_raises_a_caveat(self):
        from costmodel.explain import caveats
        cities, progs, expiry = load_all("cs")
        r = rank(Student(average_percent=85, tuition_budget=80000, housing_type="private_room"),
                 progs, cities, expiry_months=expiry, limit=1)[0]
        self.assertTrue(any("derived from the city" in c for c in caveats(r)))

    def test_every_city_has_a_rent_source(self):
        for city in self.cities.values():
            for ht in ("shared_room", "private_room", "studio"):
                self.assertTrue(city.rent(ht, "near").source, city.city)


class TestUPass(unittest.TestCase):
    """A U-Pass bundled into student fees is not a separate monthly transit cost."""

    def setUp(self):
        self.cities, self.progs, self.expiry = load_all("cs")
        self.by = {p.university_id: p for p in self.progs}
        self.student = Student(average_percent=85, tuition_budget=80000, proximity="far")

    def _est(self, uid):
        prog = self.by[uid]
        return estimate_cost(prog, self.cities[prog.city], self.student, self.expiry)

    def test_upass_school_pays_no_transit(self):
        transit = self._est("usask").monthly["transit"]
        self.assertEqual((transit.low, transit.high), (0, 0))
        self.assertIn("U-Pass", transit.source)

    def test_school_without_a_upass_still_pays_fares(self):
        # TMU has no transit pass in its compulsory fees.
        self.assertGreater(self._est("tmu").monthly["transit"].high, 0)

    def test_upass_lowers_the_living_estimate(self):
        # Same city, same housing: the only difference is the pass.
        prog = self.by["usask"]
        city = self.cities[prog.city]
        with_pass = estimate_cost(prog, city, self.student, self.expiry)
        from dataclasses import replace
        without = estimate_cost(replace(prog, upass=None), city, self.student, self.expiry)
        self.assertLess(with_pass.living_high, without.living_high)

    def test_card_says_transit_is_covered(self):
        from costmodel.explain import housing_line
        r = [x for x in rank(self.student, self.progs, self.cities, expiry_months=self.expiry)
             if x["program"].university_id == "usask"][0]
        self.assertIn("covered by the U-Pass", housing_line(r, self.student))

    def test_transit_is_free_exactly_when_a_upass_is_confirmed(self):
        for uid, prog in self.by.items():
            free = self._est(uid).monthly["transit"].high == 0
            self.assertEqual(free, prog.upass.value is True, uid)

    def test_a_school_left_blank_keeps_its_reasoning(self):
        # Memorial: a U-Pass was voted down in 2019 and nothing current confirms either way.
        mun = self.by["mun"]
        self.assertIsNone(mun.upass.value)
        self.assertIn("2019", mun.upass.source)
        self.assertGreater(self._est("mun").monthly["transit"].high, 0)


class TestFoodData(unittest.TestCase):
    """Groceries come from a provincial table, and the difference is labelled."""

    def setUp(self):
        self.cities, _, _ = load_all()

    def test_provincial_figures_applied(self):
        self.assertEqual((self.cities["Vancouver"].costs["food"].low,
                          self.cities["Vancouver"].costs["food"].high), (400, 550))
        self.assertEqual((self.cities["Saskatoon"].costs["food"].low,
                          self.cities["Saskatoon"].costs["food"].high), (330, 450))

    def test_cities_in_one_province_share_the_figure(self):
        toronto, ottawa = self.cities["Toronto"].costs["food"], self.cities["Ottawa"].costs["food"]
        self.assertEqual((toronto.low, toronto.high), (ottawa.low, ottawa.high))

    def test_every_city_carries_the_source(self):
        for city in self.cities.values():
            self.assertIn("Groceries only", city.costs["food"].source)

    def test_card_flags_groceries_only(self):
        from costmodel.explain import caveats
        cities, progs, expiry = load_all("cs")
        r = rank(Student(average_percent=85, tuition_budget=80000), progs, cities, expiry_months=expiry, limit=1)[0]
        self.assertTrue(any("groceries only" in c for c in caveats(r)))


class TestEatingOut(unittest.TestCase):
    """Meals out are priced per meal and only counted when the student eats out."""

    def setUp(self):
        self.cities, self.progs, self.expiry = load_all("cs")
        self.prog = {p.university_id: p for p in self.progs}["usask"]
        self.city = self.cities["Saskatoon"]

    def _est(self, meals):
        return estimate_cost(self.prog, self.city,
                             Student(average_percent=85, tuition_budget=50000, meals_out_per_week=meals),
                             self.expiry)

    def test_no_meals_means_no_line(self):
        self.assertNotIn("eating_out", self._est(0).monthly)

    def test_meal_price_times_frequency(self):
        est = self._est(3)  # $20-30 x 3 meals x 4.33 weeks x 12 months
        eo = est.monthly["eating_out"]
        self.assertAlmostEqual(eo.low, 20 * 3 * 4.33 * 12, places=2)
        self.assertAlmostEqual(eo.high, 30 * 3 * 4.33 * 12, places=2)

    def test_more_meals_costs_more(self):
        self.assertLess(self._est(1).living_high, self._est(5).living_high)

    def test_rejects_impossible_frequency(self):
        with self.assertRaises(ValueError):
            Student(average_percent=85, tuition_budget=50000, meals_out_per_week=30)

    def test_card_states_the_assumption(self):
        from costmodel.explain import caveats, housing_line
        student = Student(average_percent=85, tuition_budget=80000, meals_out_per_week=2)
        r = [x for x in rank(student, self.progs, self.cities, expiry_months=self.expiry)
             if x["program"].university_id == "usask"][0]
        self.assertIn("2 meals out a week at $20–30 each", housing_line(r, student))
        self.assertTrue(any("not adjusted per city" in c for c in caveats(r)))

    def test_calibration_uses_the_reported_frequency(self):
        rows = [{"city": "Saskatoon", "housing_type": "private_room", "proximity": "near",
                 "rent": None, "food": None, "transit": None, "phone_internet": None, "other": None,
                 "eating_out": 20 * 3 * 4.33, "meals_out_per_week": 3}]
        result = calibrate(self.cities, rows)
        self.assertEqual(result["per_category"]["eating_out"]["n"], 1)
        self.assertEqual(result["per_category"]["eating_out"]["coverage"], 1.0)


class TestImportedData(unittest.TestCase):
    """The three degrees filled from the workbook carry real, sourced figures."""

    FILLED = ("cs", "business", "nursing")

    def test_tuition_is_sourced_for_the_filled_degrees(self):
        for deg in self.FILLED:
            sourced = [p for p in load_programs(deg) if p.tuition_intl_annual.verified]
            self.assertGreaterEqual(len(sourced), 14, deg)
            for p in sourced:
                self.assertTrue(p.tuition_intl_annual.source_url.startswith("http"), p.id)

    def test_real_tuition_spread_is_wide(self):
        fees = [p.tuition_intl_annual.value for p in load_programs("cs") if p.tuition_intl_annual.verified]
        self.assertGreater(max(fees) - min(fees), 30000)

    def test_quebec_domestic_rate_is_flagged_for_domestic_students(self):
        from costmodel.explain import caveats
        cities, progs, expiry = load_all("business")
        results = rank(Student(average_percent=90, tuition_budget=60000, status="domestic"),
                       progs, cities, expiry_months=expiry)
        mcgill = next(r for r in results if r["program"].university_id == "mcgill")
        usask = next(r for r in results if r["program"].university_id == "usask")
        self.assertTrue(any("Quebec-resident rate" in c for c in caveats(mcgill)))
        self.assertFalse(any("Quebec-resident rate" in c for c in caveats(usask)))

    def test_that_flag_is_absent_for_international_students(self):
        from costmodel.explain import caveats
        cities, progs, expiry = load_all("business")
        results = rank(Student(average_percent=90, tuition_budget=60000, status="international"),
                       progs, cities, expiry_months=expiry)
        mcgill = next(r for r in results if r["program"].university_id == "mcgill")
        self.assertFalse(any("Quebec-resident" in c for c in caveats(mcgill)))


class TestAssistant(unittest.TestCase):
    """The model fills in the form and writes prose. It never supplies a figure."""

    def setUp(self):
        from costmodel import assistant
        self.a = assistant
        self.degrees = set(load_degrees().keys())

    def _with_reply(self, text):
        """Run the assistant against a canned reply — no network in tests."""
        import contextlib, unittest.mock as mock
        return mock.patch.object(self.a, "_call", return_value=text)

    def test_disabled_without_a_key(self):
        import unittest.mock as mock
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(self.a.enabled())
            with self.assertRaises(self.a.GeminiError):
                self.a._call("hi")

    def test_parses_a_sentence_into_fields(self):
        reply = '{"average": 78, "tuition_budget": 30000, "degree": "cs", "coop": true, "city_size": "small"}'
        with self._with_reply(reply):
            out = self.a.parse_query("78% average, $30k tuition, CS with co-op, small city", self.degrees)
        self.assertEqual(out, {"average": 78.0, "budget": 30000.0, "degree": "cs",
                               "coop": True, "city_size": "small"})

    def test_drops_values_the_app_cannot_use(self):
        reply = ('{"average": 250, "degree": "astrology", "housing_type": "castle", '
                 '"city_size": "enormous", "meals_out": 99, "status": "martian"}')
        with self._with_reply(reply):
            self.assertEqual(self.a.parse_query("nonsense", self.degrees), {})

    def test_survives_prose_around_the_json(self):
        with self._with_reply('Sure! ```json\n{"average": 85}\n```'):
            self.assertEqual(self.a.parse_query("85 average", self.degrees), {"average": 85.0})

    def test_empty_query_never_calls_the_model(self):
        import unittest.mock as mock
        with mock.patch.object(self.a, "_call", side_effect=AssertionError("should not be called")):
            self.assertEqual(self.a.parse_query("   ", self.degrees), {})

    def _results(self):
        cities, progs, expiry = load_all("cs")
        return rank(Student(average_percent=88, tuition_budget=70000), progs, cities,
                    expiry_months=expiry, limit=3)

    def test_summary_passes_through_when_it_uses_our_numbers(self):
        results = self._results()
        facts = self.a._facts(results)
        top = results[0]
        good = (f"All three sit inside your budget, with tuition from "
                f"${top['estimate'].tuition.value:,.0f} upward.")
        with self._with_reply(good):
            self.assertIsNotNone(self.a.summarise(results))

    def test_summary_is_dropped_when_it_invents_a_figure(self):
        results = self._results()
        with self._with_reply("Expect to pay about $41,250 a year in rent across these schools."):
            self.assertIsNone(self.a.summarise(results))

    def test_summary_is_dropped_when_it_rounds_our_figure(self):
        results = self._results()
        with self._with_reply("Tuition starts around $66,000 a year."):
            self.assertIsNone(self.a.summarise(results))

    def test_years_and_counts_are_allowed_through(self):
        results = self._results()
        ok = ("All three of these clear your budget, and the 2026 subject rankings put them "
              "within a few points of each other.")
        with self._with_reply(ok):
            self.assertIsNotNone(self.a.summarise(results))

    def test_no_results_means_no_summary(self):
        self.assertIsNone(self.a.summarise([]))

    def test_facts_flag_unconfirmed_tuition(self):
        cities, progs, expiry = load_all("nursing")
        results = rank(Student(average_percent=88, tuition_budget=70000), progs, cities, expiry_months=expiry)
        unconfirmed = [r for r in results if not r["estimate"].tuition.verified]
        if unconfirmed:
            self.assertIn("(unconfirmed)", self.a._facts(unconfirmed[:1]))


class AssistantGuards(unittest.TestCase):
    """The model integration, without touching the network."""

    def setUp(self):
        from costmodel import assistant
        self.a = assistant
        assistant._resolved = None
        assistant._bad.clear()

    def test_a_degree_name_is_accepted_as_well_as_its_id(self):
        _, lookup = self.a._degree_index(load_degrees())
        self.assertEqual(self.a._clean({"degree": "Computer Science"}, lookup)["degree"], "cs")
        self.assertEqual(self.a._clean({"degree": "cs"}, lookup)["degree"], "cs")
        self.assertNotIn("degree", self.a._clean({"degree": "underwater welding"}, lookup))

    def test_a_reasoning_only_response_raises_instead_of_looking_empty(self):
        payload = {"candidates": [{"content": {"parts": [{"thought": True, "text": "..."}]},
                                   "finishReason": "MAX_TOKENS"}]}
        with self.assertRaises(self.a.GeminiError):
            self.a._extract(payload)

    def test_thinking_parts_are_stripped_from_the_answer(self):
        payload = {"candidates": [{"content": {"parts": [{"thought": True, "text": "reasoning"},
                                                         {"text": "{\"average\": 85}"}]}}]}
        self.assertEqual(self.a._extract(payload), '{"average": 85}')

    def test_a_retired_model_falls_back_to_the_one_google_names(self):
        calls = []

        def fake_post(model, *args, **kwargs):
            calls.append(model)
            if model == "gemini-3.6-flash":
                raise self.a.GeminiError(
                    "HTTP 404: This model models/gemini-3.6-flash is no longer available. "
                    "Please update your code to use models/gemini-4-flash")
            return "ok"

        original_post, original_key = self.a._post, self.a.api_key
        self.a._post, self.a.api_key = fake_post, lambda: "test"
        try:
            self.assertEqual(self.a._call("hello"), "ok")
        finally:
            self.a._post, self.a.api_key = original_post, original_key
        self.assertEqual(calls, ["gemini-3.6-flash", "gemini-4-flash"])

    def test_a_busy_model_is_retried_then_swapped(self):
        self.a.RETRY_PAUSE = 0.001
        calls = []

        def flaky(model, *args, **kwargs):
            calls.append(model)
            if len(calls) < 3:
                raise self.a.GeminiError("HTTP 503: This model is currently experiencing high demand.")
            return "ok"

        original = (self.a._post, self.a.api_key, self.a.list_models)
        self.a._post, self.a.api_key = flaky, lambda: "test"
        self.a.list_models = lambda: ["gemini-3.6-flash", "gemini-flash-latest"]
        try:
            self.assertEqual(self.a._call("hello"), "ok")
        finally:
            self.a._post, self.a.api_key, self.a.list_models = original
        self.assertEqual(len(calls), 3)
        self.assertNotEqual(calls[-1], calls[0])   # moved to a different model

    def test_a_model_busy_throughout_says_so_in_plain_words(self):
        self.a.RETRY_PAUSE = 0.001

        def busy(*args, **kwargs):
            raise self.a.GeminiError("HTTP 503: high demand")

        original = (self.a._post, self.a.api_key)
        self.a._post, self.a.api_key = busy, lambda: "test"
        try:
            with self.assertRaises(self.a.GeminiError) as caught:
                self.a._call("hello")
        finally:
            self.a._post, self.a.api_key = original
        self.assertIn("busy", str(caught.exception))
        self.assertNotIn("HTTP", str(caught.exception))

    def test_json_mode_is_dropped_when_the_model_refuses_under_load(self):
        self.a.RETRY_PAUSE = 0.001
        modes = []

        def fussy(model, prompt, temperature, max_tokens, *, json_only=False, thinking=False):
            modes.append(json_only)
            if json_only:
                raise self.a.GeminiError("HTTP 503: This model is currently experiencing high demand.")
            return '{"average": 85}'

        original = (self.a._post, self.a.api_key)
        self.a._post, self.a.api_key = fussy, lambda: "test"
        try:
            out = self.a.parse_query("85% average", load_degrees())
        finally:
            self.a._post, self.a.api_key = original
        self.assertEqual(out, {"average": 85.0})
        self.assertEqual(modes, [True, False])

    def test_an_invented_cost_is_still_rejected(self):
        facts = "- Toronto: tuition $66,110, living $22,958-$36,178"
        self.assertIsNone(self.a._invented_number("Tuition is $66,110 there.", facts))
        self.assertEqual(self.a._invented_number("Tuition is about $66,000.", facts), "$66,000")


class AssistantBudget(unittest.TestCase):
    """The assistant's call budget, which protects a free-tier key."""

    def setUp(self):
        from costmodel import ratelimit
        self.r = ratelimit
        ratelimit.reset()
        self._per_visitor = ratelimit.PER_VISITOR
        self._per_hour = ratelimit.PER_HOUR

    def tearDown(self):
        self.r.PER_VISITOR, self.r.PER_HOUR = self._per_visitor, self._per_hour
        self.r.reset()

    def test_a_visitor_gets_a_fixed_number_of_calls(self):
        self.r.PER_VISITOR = 3
        self.assertTrue(all(self.r.allow("1.1.1.1") for _ in range(3)))
        self.assertFalse(self.r.allow("1.1.1.1"))
        self.assertEqual(self.r.remaining("1.1.1.1"), 0)

    def test_one_visitor_running_out_does_not_affect_another(self):
        self.r.PER_VISITOR = 2
        self.assertTrue(self.r.allow("1.1.1.1"))
        self.assertTrue(self.r.allow("1.1.1.1"))
        self.assertFalse(self.r.allow("1.1.1.1"))
        self.assertTrue(self.r.allow("2.2.2.2"))

    def test_an_hourly_ceiling_caps_everyone_together(self):
        self.r.PER_VISITOR, self.r.PER_HOUR = 10, 4
        self.assertTrue(all(self.r.allow(f"visitor-{i}") for i in range(4)))
        self.assertFalse(self.r.allow("someone-new"))

    def test_the_ranking_itself_is_never_rate_limited(self):
        """The guard sits on assistant.summarise / parse_query, not on rank()."""
        source = (pathlib.Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
        for line in source.splitlines():
            if "ratelimit.allow" in line:
                self.assertIn("assistant", line.lower() + source[source.index(line):source.index(line) + 400].lower())
