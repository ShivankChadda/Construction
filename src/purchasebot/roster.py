"""Who is who: sites, people (by WhatsApp number) and known vendors.

The roster is a small YAML file the office edits by hand. Phone numbers are
the identity: WhatsApp authenticates the sender, so a message from the
approver's number is treated as the approver.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = {"engineer", "logistics", "approver", "observer"}


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 10:  # bare Indian mobile number
        digits = "91" + digits
    return digits


@dataclass(frozen=True)
class Site:
    code: str  # NIC
    name: str  # Nicobar
    letter: str  # N  (prefix for item refs like N17)
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Person:
    name: str
    phone: str
    role: str
    site: str = ""  # engineers only
    initials: str = ""
    title: str = ""

    @property
    def short_phone(self) -> str:
        return f"+{self.phone[:2]} XXXXX X{self.phone[-4:]}" if len(self.phone) >= 6 else self.phone


@dataclass(frozen=True)
class Vendor:
    name: str
    aliases: tuple[str, ...] = ()
    phone: str = ""


@dataclass
class Company:
    name: str = "Your Company"
    address: str = ""
    gstin: str = ""


@dataclass
class Roster:
    company: Company
    sites: list[Site]
    people: list[Person]
    vendors: list[Vendor] = field(default_factory=list)

    # ---- lookups ----
    def person(self, phone: str) -> Person | None:
        p = normalize_phone(phone)
        return next((x for x in self.people if x.phone == p), None)

    def by_role(self, role: str) -> list[Person]:
        return [x for x in self.people if x.role == role]

    def site(self, code: str) -> Site | None:
        return next((s for s in self.sites if s.code == code), None)

    def site_name(self, code: str) -> str:
        s = self.site(code)
        return s.name if s else code

    def engineers_for(self, site_code: str) -> list[Person]:
        return [x for x in self.people if x.role == "engineer" and x.site == site_code]

    def find_site(self, text: str) -> Site | None:
        """Match 'Nicobar', 'nic', 'Kamorta', 'Komoota' (fuzzy) to a site."""
        t = text.strip().lower()
        if not t:
            return None
        for s in self.sites:
            names = {s.code.lower(), s.name.lower(), *[a.lower() for a in s.aliases]}
            if t in names:
                return s
        candidates = {n: s for s in self.sites for n in (s.name.lower(), *[a.lower() for a in s.aliases])}
        match = difflib.get_close_matches(t, list(candidates), n=1, cutoff=0.75)
        return candidates[match[0]] if match else None

    def find_site_in_text(self, text: str) -> Site | None:
        """The one site a message talks about ("Diglipur site requirements", "Car Nicobar Sector",
        "ship to C/N"). None if no site or more than one is mentioned."""
        t = text.lower()
        hits = set()
        for s in self.sites:
            for n in (s.name, *s.aliases):
                if re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", t):
                    hits.add(s.code)
        return self.site(hits.pop()) if len(hits) == 1 else None

    def site_by_letter(self, letter: str) -> Site | None:
        return next((s for s in self.sites if s.letter.upper() == letter.upper()), None)

    def match_vendor(self, raw: str) -> Vendor | None:
        t = re.sub(r"[^a-z0-9 ]", "", raw.lower()).strip()
        if not t:
            return None
        for v in self.vendors:
            names = [v.name.lower(), *[a.lower() for a in v.aliases]]
            if t in [re.sub(r"[^a-z0-9 ]", "", n) for n in names]:
                return v
        pool = {re.sub(r"[^a-z0-9 ]", "", n.lower()): v for v in self.vendors for n in (v.name, *v.aliases)}
        match = difflib.get_close_matches(t, list(pool), n=1, cutoff=0.8)
        return pool[match[0]] if match else None


def load_roster(path: str | Path) -> Roster:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return roster_from_dict(data)


def roster_from_dict(data: dict) -> Roster:
    company = Company(**(data.get("company") or {}))
    sites = [
        Site(
            code=str(s["code"]).upper(),
            name=s["name"],
            letter=str(s.get("letter") or s["code"][0]).upper(),
            aliases=tuple(s.get("aliases") or ()),
        )
        for s in data.get("sites") or []
    ]
    site_codes = {s.code for s in sites}
    letters = [s.letter for s in sites]
    if len(set(letters)) != len(letters):
        raise ValueError("Each site needs a unique 'letter' (used for item refs like N17).")

    people: list[Person] = []
    seen: set[str] = set()
    for p in data.get("people") or []:
        role = p["role"]
        if role not in ROLES:
            raise ValueError(f"Unknown role {role!r} for {p.get('name')}; use one of {sorted(ROLES)}")
        phone = normalize_phone(p["phone"])
        if phone in seen:
            raise ValueError(f"Phone {phone} appears twice in the roster")
        seen.add(phone)
        site = str(p.get("site") or "").upper()
        if role == "engineer" and site not in site_codes:
            raise ValueError(f"Engineer {p['name']} must have a site from {sorted(site_codes)}")
        people.append(
            Person(
                name=p["name"],
                phone=phone,
                role=role,
                site=site,
                initials=p.get("initials") or "".join(w[0] for w in p["name"].split()[:3]).upper(),
                title=p.get("title") or "",
            )
        )
    if not any(p.role == "approver" for p in people):
        raise ValueError("The roster needs at least one person with role: approver")

    vendors = [
        Vendor(name=v["name"], aliases=tuple(v.get("aliases") or ()), phone=normalize_phone(v.get("phone", "")))
        for v in data.get("vendors") or []
    ]
    return Roster(company=company, sites=sites, people=people, vendors=vendors)
