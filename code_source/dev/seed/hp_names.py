"""Noms fictifs (univers Harry Potter) pour les données de développement — aucune donnée réelle."""

# Encadrants (collection `coaches`) : l'ordre fixe les identifiants, Snape est le premier (id 1).
COACHES = [
    "Severus Snape",
    "Minerva McGonagall",
    "Filius Flitwick",
    "Pomona Sprout",
    "Remus Lupin",
    "Rubeus Hagrid",
]

# Élèves de Poudlard : (prénom, nom, sexe) — adhérents « jeunes »
STUDENTS = [
    ("Harry", "Potter", "M"), ("Ginny", "Weasley", "F"), ("Ron", "Weasley", "M"),
    ("Hermione", "Granger", "F"), ("Fred", "Weasley", "M"), ("George", "Weasley", "M"),
    ("Neville", "Longbottom", "M"), ("Luna", "Lovegood", "F"), ("Draco", "Malfoy", "M"),
    ("Cho", "Chang", "F"), ("Cedric", "Diggory", "M"), ("Seamus", "Finnigan", "M"),
    ("Dean", "Thomas", "M"), ("Lavender", "Brown", "F"), ("Parvati", "Patil", "F"),
    ("Padma", "Patil", "F"), ("Colin", "Creevey", "M"), ("Dennis", "Creevey", "M"),
    ("Hannah", "Abbott", "F"), ("Ernie", "Macmillan", "M"), ("Justin", "Finch-Fletchley", "M"),
    ("Susan", "Bones", "F"), ("Katie", "Bell", "F"), ("Angelina", "Johnson", "F"),
    ("Oliver", "Wood", "M"), ("Lee", "Jordan", "M"), ("Gregory", "Goyle", "M"),
    ("Vincent", "Crabbe", "M"), ("Pansy", "Parkinson", "F"), ("Blaise", "Zabini", "M"),
    ("Theodore", "Nott", "M"), ("Romilda", "Vane", "F"), ("Cormac", "McLaggen", "M"),
    ("Michael", "Corner", "M"), ("Terry", "Boot", "M"), ("Marietta", "Edgecombe", "F"),
    ("Astoria", "Greengrass", "F"), ("Daphne", "Greengrass", "F"), ("Millicent", "Bulstrode", "F"),
    ("Zacharias", "Smith", "M"), ("Gabrielle", "Delacour", "F"), ("Teddy", "Lupin", "M"),
]

# Adultes (parents, anciens élèves, personnel) — adhérents « adultes »
ADULTS = [
    ("Molly", "Weasley", "F"), ("Arthur", "Weasley", "M"), ("Bill", "Weasley", "M"),
    ("Charlie", "Weasley", "M"), ("Percy", "Weasley", "M"), ("Sirius", "Black", "M"),
    ("Nymphadora", "Tonks", "F"), ("Kingsley", "Shacklebolt", "M"), ("Alastor", "Moody", "M"),
    ("Fleur", "Delacour", "F"), ("Viktor", "Krum", "M"), ("Lucius", "Malfoy", "M"),
    ("Narcissa", "Malfoy", "F"), ("Xenophilius", "Lovegood", "M"), ("Augusta", "Longbottom", "F"),
    ("Horace", "Slughorn", "M"), ("Sybill", "Trelawney", "F"), ("Rolanda", "Hooch", "F"),
    ("Poppy", "Pomfrey", "F"), ("Argus", "Filch", "M"),
]

# Responsables légaux (payeurs) des jeunes, par nom de famille ; à défaut, Faker invente un prénom.
PARENTS = {
    "Weasley": "Molly", "Malfoy": "Narcissa", "Longbottom": "Augusta", "Lovegood": "Xenophilius",
    "Granger": "Jean", "Potter": "Lily", "Delacour": "Apolline", "Lupin": "Remus",
}
