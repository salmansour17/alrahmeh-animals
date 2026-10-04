"""Sample animals, so a fresh install has animal pages to look at.

They are added once, at startup, only while the database has no animals at
all, and through AnimalService like any staff entry, so every rule that
validates a real intake validates these too. Set SAMPLE_ANIMALS=0 to start
with an empty database instead (config.py).

Dates are counted back from the service's own "today", so the samples are
never dated in the future, whatever day the app is installed.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from domains.animals.service import AnimalService

logger = logging.getLogger(__name__)

# name, species, breed, days since intake, profile, medical records
# (type, description, days ago), and the placement moves after intake.
SAMPLES = [
    {
        "animal": ("Luna", "Cat", "Domestic shorthair", 40),
        "profile": ("Grey tabby", "Calm and affectionate", "3.8", 700,
                    "Luna was found under a car in Madaba. She loves a sunny windowsill "
                    "and will purr the moment you sit down next to her."),
        "medical": [("vaccination", "Rabies", 35), ("vaccination", "FVRCP", 35), ("checkup", "Spayed", 30)],
        "moves": [],
    },
    {
        "animal": ("Simba", "Kitten", "Mixed", 12),
        "profile": ("Ginger", "Playful and curious", "1.2", 100,
                    "Simba arrived with his two sisters, who have already found homes. "
                    "He chases anything that moves and naps just as hard."),
        "medical": [("vaccination", "FVRCP (first dose)", 10)],
        "moves": [],
    },
    {
        "animal": ("Rocky", "Dog", "Canaan dog mix", 90),
        "profile": ("Sandy", "Loyal and gentle", "18.5", 1100,
                    "Rocky is a quiet giant who walks well on a lead and gets on with other "
                    "dogs. He would love a home with a garden."),
        "medical": [("vaccination", "Rabies", 85), ("vaccination", "DHPP", 85), ("treatment", "Tick treatment", 60)],
        "moves": [],
    },
    {
        "animal": ("Bella", "Dog", "Saluki mix", 25),
        "profile": ("Cream", "Shy at first, then devoted", "14", 550,
                    "Bella was rescued from the roadside near Amman. She takes a day to trust "
                    "new people and then follows them everywhere."),
        "medical": [("vaccination", "Rabies", 20), ("checkup", "Healthy weight gain", 5)],
        "moves": [],
    },
    {
        "animal": ("Zaytoon", "Dog", "Mixed", 120),
        "profile": ("Black and white", "Energetic and friendly", "11", 800,
                    "Zaytoon is living with a foster family while she learns house manners. "
                    "She already knows sit, stay and paw."),
        "medical": [("vaccination", "Rabies", 115), ("vaccination", "DHPP", 115)],
        "moves": ["fostering"],
    },
    {
        "animal": ("Max", "Dog", "Labrador mix", 200),
        "profile": ("Golden", "Easy-going", "27", 1500,
                    "Max found his family after three months with us and now sends photos "
                    "from his new sofa."),
        "medical": [("vaccination", "Rabies", 190), ("vaccination", "DHPP", 190)],
        "moves": ["pending", "adopted"],
    },
]


def add_sample_animals(animals: AnimalService) -> int:
    """Admit the sample animals if there are no animals yet. Returns how many
    were added: 0 when the database already has animals of its own."""
    if animals.list_animals():
        return 0
    today = animals.today()
    for sample in SAMPLES:
        name, species, breed, intake_days = sample["animal"]
        animal = animals.admit(
            {
                "name": name,
                "species": species,
                "breed": breed,
                "intake_date": (today - timedelta(days=intake_days)).isoformat(),
                "notes": "Sample animal added at first start.",
            }
        )
        colour, personality, weight_kg, age_days, about = sample["profile"]
        animals.update_profile(
            animal.id,
            {
                "born_on": (today - timedelta(days=age_days)).isoformat(),
                "colour": colour,
                "personality": personality,
                "weight_kg": weight_kg,
                "about": about,
            },
        )
        for record_type, description, days_ago in sample["medical"]:
            animals.record_medical(
                animal.id,
                {
                    "record_type": record_type,
                    "description": description,
                    "occurred_on": (today - timedelta(days=days_ago)).isoformat(),
                },
            )
        for status in sample["moves"]:
            animals.transition(animal.id, {"to": status, "reason": "Sample history"})
    logger.info("Added %d sample animals (set SAMPLE_ANIMALS=0 to start empty)", len(SAMPLES))
    return len(SAMPLES)
