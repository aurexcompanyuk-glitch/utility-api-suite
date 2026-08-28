"""Demo venue dataset used when no BestTime key is configured.

Names are fictional — this is simulated data, so it deliberately does
not attach invented busyness numbers to real businesses. Venues are
spread across many cities so name and place search both return
meaningful results in demo mode.

Columns: name, category, street, city, lat, lng, price_level, rating
"""

VENUE_ROWS = [
    # --- London ---
    ("The Copper Kettle", "cafe", "14 High Street", "London", 51.5074, -0.1278, 2, 4.4),
    ("Bean & Barrel", "cafe", "88 Baker Street", "London", 51.5205, -0.1567, 2, 4.6),
    ("Corner Espresso", "cafe", "3 King's Road", "London", 51.4875, -0.1687, 1, 4.3),
    ("Morning Glory Cafe", "cafe", "60 Portobello Road", "London", 51.5170, -0.2040, 1, 4.2),
    ("The Daily Grind", "cafe", "21 Shoreditch High St", "London", 51.5240, -0.0778, 2, 4.5),
    ("Trattoria Milano", "restaurant", "22 Dean Street", "London", 51.5099, -0.1180, 3, 4.5),
    ("Sakura Sushi House", "restaurant", "9 Park Avenue", "London", 51.5142, -0.0931, 3, 4.7),
    ("The Gilded Fork", "restaurant", "41 Regent Street", "London", 51.5101, -0.1367, 4, 4.6),
    ("Spice Route", "restaurant", "31 Brick Lane", "London", 51.5225, -0.0715, 2, 4.4),
    ("Olive & Thyme", "restaurant", "77 Upper Street", "London", 51.5380, -0.1030, 3, 4.3),
    ("Smokehouse 41", "restaurant", "41 Camden Road", "London", 51.5390, -0.1400, 2, 4.2),
    ("Pho Lantern", "restaurant", "12 Kingsland Road", "London", 51.5300, -0.0760, 2, 4.5),
    ("The Rusty Anchor", "bar", "5 Wapping High St", "London", 51.5033, -0.1195, 2, 4.1),
    ("Blue Moon Tavern", "bar", "17 Camden High St", "London", 51.5390, -0.1426, 2, 4.0),
    ("The Velvet Room", "bar", "8 Soho Square", "London", 51.5150, -0.1320, 3, 4.4),
    ("Hopfield Brewhouse", "bar", "55 Bermondsey St", "London", 51.4990, -0.0810, 2, 4.6),

    # --- Manchester ---
    ("Northern Roast", "cafe", "12 Deansgate", "Manchester", 53.4808, -2.2426, 2, 4.5),
    ("Cotton Yard Coffee", "cafe", "4 Thomas Street", "Manchester", 53.4850, -2.2360, 2, 4.6),
    ("The Curry Mile House", "restaurant", "180 Wilmslow Road", "Manchester", 53.4500, -2.2230, 1, 4.3),
    ("Alberto's Kitchen", "restaurant", "30 King Street", "Manchester", 53.4810, -2.2450, 3, 4.4),
    ("Steel & Vine", "restaurant", "7 Spinningfields", "Manchester", 53.4795, -2.2510, 4, 4.7),
    ("The Whitworth Arms", "bar", "22 Oxford Road", "Manchester", 53.4700, -2.2340, 1, 4.0),
    ("Canal Street Social", "bar", "14 Canal Street", "Manchester", 53.4770, -2.2370, 2, 4.2),

    # --- Birmingham ---
    ("Brindley Beans", "cafe", "5 Brindleyplace", "Birmingham", 52.4785, -1.9110, 2, 4.4),
    ("The Jewellery Quarter Cafe", "cafe", "40 Vyse Street", "Birmingham", 52.4890, -1.9110, 1, 4.3),
    ("Balti House Sparkhill", "restaurant", "220 Stratford Road", "Birmingham", 52.4400, -1.8620, 1, 4.5),
    ("The Iron Grill", "restaurant", "12 Colmore Row", "Birmingham", 52.4810, -1.9010, 3, 4.4),
    ("Digbeth Taproom", "bar", "88 Digbeth High St", "Birmingham", 52.4750, -1.8850, 2, 4.3),

    # --- Leeds ---
    ("Headrow Coffee Co", "cafe", "3 The Headrow", "Leeds", 53.8008, -1.5491, 2, 4.5),
    ("Kirkgate Kitchen", "restaurant", "22 Kirkgate", "Leeds", 53.7970, -1.5410, 2, 4.4),
    ("The Calls Bistro", "restaurant", "40 The Calls", "Leeds", 53.7950, -1.5350, 3, 4.6),
    ("Belgrave Music Bar", "bar", "1 Cross Belgrave St", "Leeds", 53.8020, -1.5410, 2, 4.4),

    # --- Edinburgh ---
    ("Royal Mile Roasters", "cafe", "88 High Street", "Edinburgh", 55.9500, -3.1870, 2, 4.6),
    ("Stockbridge Sourdough", "cafe", "6 Raeburn Place", "Edinburgh", 55.9590, -3.2100, 2, 4.7),
    ("The Haggis Table", "restaurant", "14 Grassmarket", "Edinburgh", 55.9470, -3.1960, 3, 4.5),
    ("Leith Seafood Room", "restaurant", "2 The Shore", "Edinburgh", 55.9750, -3.1700, 4, 4.8),
    ("The Thistle Vaults", "bar", "30 Cowgate", "Edinburgh", 55.9480, -3.1900, 2, 4.1),

    # --- Bristol ---
    ("Harbourside Brew", "cafe", "9 Wapping Wharf", "Bristol", 51.4480, -2.6000, 2, 4.5),
    ("Stokes Croft Coffee", "cafe", "55 Stokes Croft", "Bristol", 51.4620, -2.5900, 1, 4.4),
    ("Clifton Supper Club", "restaurant", "12 Princess Victoria St", "Bristol", 51.4540, -2.6200, 3, 4.6),
    ("The Cider Press", "bar", "18 King Street", "Bristol", 51.4510, -2.5950, 2, 4.3),

    # --- Glasgow / Liverpool / Newcastle ---
    ("Merchant City Coffee", "cafe", "20 Candleriggs", "Glasgow", 55.8580, -4.2450, 2, 4.5),
    ("The Finnieston Grill", "restaurant", "1160 Argyle Street", "Glasgow", 55.8650, -4.2870, 3, 4.7),
    ("Sub Club Bar", "bar", "22 Jamaica Street", "Glasgow", 55.8570, -4.2580, 2, 4.2),
    ("Bold Street Beans", "cafe", "40 Bold Street", "Liverpool", 53.4030, -2.9800, 2, 4.6),
    ("The Albert Dock Table", "restaurant", "5 Albert Dock", "Liverpool", 53.4000, -2.9920, 3, 4.4),
    ("Quayside Coffee", "cafe", "3 Quayside", "Newcastle", 54.9700, -1.6020, 2, 4.4),
    ("Jesmond Supper Room", "restaurant", "88 Osborne Road", "Newcastle", 54.9880, -1.6000, 3, 4.5),

    # --- Oxford / Cambridge / Brighton / York ---
    ("Radcliffe Roasters", "cafe", "7 Broad Street", "Oxford", 51.7540, -1.2570, 2, 4.5),
    ("The Cherwell Table", "restaurant", "12 Bardwell Road", "Oxford", 51.7680, -1.2600, 3, 4.6),
    ("Mill Lane Coffee", "cafe", "4 Mill Lane", "Cambridge", 52.2020, 0.1180, 2, 4.5),
    ("The Backs Bistro", "restaurant", "9 Trumpington St", "Cambridge", 52.2010, 0.1170, 3, 4.5),
    ("Lanes Espresso", "cafe", "12 Ship Street", "Brighton", 50.8220, -0.1420, 2, 4.6),
    ("Seafront Kitchen", "restaurant", "1 Kings Road Arches", "Brighton", 50.8200, -0.1480, 2, 4.3),
    ("The Shambles Coffee", "cafe", "8 The Shambles", "York", 53.9590, -1.0810, 2, 4.7),
    ("Minster Supper Club", "restaurant", "3 Deangate", "York", 53.9620, -1.0810, 3, 4.5),

    # --- International ---
    ("Le Petit Comptoir", "cafe", "18 Rue de Rivoli", "Paris", 48.8560, 2.3560, 2, 4.5),
    ("Bistro Saint-Germain", "restaurant", "44 Bd Saint-Germain", "Paris", 48.8530, 2.3440, 3, 4.6),
    ("Kaffeehaus Mitte", "cafe", "10 Torstrasse", "Berlin", 52.5290, 13.4020, 2, 4.4),
    ("Brooklyn Roasting Room", "cafe", "25 Bedford Ave", "New York", 40.7180, -73.9570, 2, 4.5),
    ("Midtown Chophouse", "restaurant", "400 W 42nd Street", "New York", 40.7590, -73.9930, 4, 4.6),
    ("Mission Taqueria", "restaurant", "2100 Mission St", "San Francisco", 37.7620, -122.4190, 1, 4.5),
    ("Pike Place Perk", "cafe", "90 Pike Street", "Seattle", 47.6090, -122.3410, 2, 4.4),
]
