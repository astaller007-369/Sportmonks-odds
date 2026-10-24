# (sportmonks_league_id, country, league)
LEAGUES = [
    (453, "Poland", "Ekstraklasa"), (648, "Brazil", "Serie A"),
    (82, "Germany", "Bundesliga"), (85, "Germany", "2. Bundesliga"),
    (301, "France", "Ligue 1"), (304, "France", "Ligue 2"),
    (462, "Portugal", "Liga Portugal"), (564, "Spain", "La Liga"),
    (567, "Spain", "La Liga 2"), (72, "Netherlands", "Eredivisie"),
    (74, "Netherlands", "Eerste Divisie"), (573, "Sweden", "Allsvenskan"),
    (325, "Greece", "Super League"), (591, "Switzerland", "Super League"),
    (1034, "South Korea", "K League 1"), (181, "Austria", "Admiral Bundesliga"),
    (486, "Russia", "Premier League"), (384, "Italy", "Serie A"),
    (387, "Italy", "Serie B"), (271, "Denmark", "Superliga"),
    (672, "Colombia", "Liga BetPlay"), (600, "Turkey", "Super Lig"),
    (360, "Republic of Ireland", "Premier Division"), (8, "England", "Premier League"),
    (9, "England", "Championship"), (968, "Japan", "J1 League"),
    (208, "Belgium", "Pro League"), (531, "Serbia", "Super Liga"),
    (501, "Scotland", "Premiership"), (444, "Norway", "Eliteserien"),
    (609, "Ukraine", "Premier League"), (830, "Egypt", "Premier League"),
    (806, "South Africa", "Premier League"), (1064, "Thailand", "Thai Premier League"),
    (743, "Mexico", "Liga MX"), (334, "Hungary", "NB 1"),
    (944, "Saudi Arabia", "Pro League"), (696, "Ecuador", "Liga Pro"),
    (474, "Romania", "Superliga"), (229, "Bulgaria", "First League"),
    (465, "Portugal", "Liga Portugal 2"), (244, "Croatia", "1. HNL"),
    (262, "Czech Republic", "Chance Liga"),
]


def label(lid, country, name):
    return f"{country} – {name} ({lid})"
