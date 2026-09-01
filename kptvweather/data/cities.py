#!/usr/bin/env python3
"""
City Table Module

A compact table of populous cities used to pick the markers plotted on the
regional and forecast map pages, and to put a name on a station configured
by raw coordinates.

Kept deliberately small: the maps only ever show a handful of markers, so a
few hundred well spread cities cover far more than they need to without
dragging a multi-megabyte gazetteer into the image.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Optional

from ..utils import haversine_miles

# name, latitude, longitude
CITIES = (
    ("New York, NY", 40.7128, -74.0060),
    ("Brooklyn, NY", 40.6782, -73.9442),
    ("Newark, NJ", 40.7357, -74.1724),
    ("Jersey City, NJ", 40.7178, -74.0431),
    ("Yonkers, NY", 40.9312, -73.8988),
    ("Bridgeport, CT", 41.1792, -73.1894),
    ("New Haven, CT", 41.3083, -72.9279),
    ("Hartford, CT", 41.7658, -72.6734),
    ("Providence, RI", 41.8240, -71.4128),
    ("Boston, MA", 42.3601, -71.0589),
    ("Worcester, MA", 42.2626, -71.8023),
    ("Springfield, MA", 42.1015, -72.5898),
    ("Manchester, NH", 42.9956, -71.4548),
    ("Portland, ME", 43.6591, -70.2568),
    ("Burlington, VT", 44.4759, -73.2121),
    ("Albany, NY", 42.6526, -73.7562),
    ("Syracuse, NY", 43.0481, -76.1474),
    ("Rochester, NY", 43.1566, -77.6088),
    ("Buffalo, NY", 42.8864, -78.8784),
    ("Erie, PA", 42.1292, -80.0851),
    ("Pittsburgh, PA", 40.4406, -79.9959),
    ("Philadelphia, PA", 39.9526, -75.1652),
    ("Allentown, PA", 40.6084, -75.4902),
    ("Scranton, PA", 41.4090, -75.6624),
    ("Harrisburg, PA", 40.2732, -76.8867),
    ("Wilmington, DE", 39.7391, -75.5398),
    ("Baltimore, MD", 39.2904, -76.6122),
    ("Washington, DC", 38.9072, -77.0369),
    ("Richmond, VA", 37.5407, -77.4360),
    ("Virginia Beach, VA", 36.8529, -75.9780),
    ("Norfolk, VA", 36.8508, -76.2859),
    ("Raleigh, NC", 35.7796, -78.6382),
    ("Charlotte, NC", 35.2271, -80.8431),
    ("Greensboro, NC", 36.0726, -79.7920),
    ("Asheville, NC", 35.5951, -82.5515),
    ("Columbia, SC", 34.0007, -81.0348),
    ("Charleston, SC", 32.7765, -79.9311),
    ("Savannah, GA", 32.0809, -81.0912),
    ("Atlanta, GA", 33.7490, -84.3880),
    ("Augusta, GA", 33.4735, -82.0105),
    ("Jacksonville, FL", 30.3322, -81.6557),
    ("Orlando, FL", 28.5383, -81.3792),
    ("Tampa, FL", 27.9506, -82.4572),
    ("Miami, FL", 25.7617, -80.1918),
    ("Fort Lauderdale, FL", 26.1224, -80.1373),
    ("Tallahassee, FL", 30.4383, -84.2807),
    ("Birmingham, AL", 33.5186, -86.8104),
    ("Montgomery, AL", 32.3668, -86.3000),
    ("Mobile, AL", 30.6954, -88.0399),
    ("Jackson, MS", 32.2988, -90.1848),
    ("New Orleans, LA", 29.9511, -90.0715),
    ("Baton Rouge, LA", 30.4515, -91.1871),
    ("Shreveport, LA", 32.5252, -93.7502),
    ("Little Rock, AR", 34.7465, -92.2896),
    ("Memphis, TN", 35.1495, -90.0490),
    ("Nashville, TN", 36.1627, -86.7816),
    ("Knoxville, TN", 35.9606, -83.9207),
    ("Chattanooga, TN", 35.0456, -85.3097),
    ("Louisville, KY", 38.2527, -85.7585),
    ("Lexington, KY", 38.0406, -84.5037),
    ("Charleston, WV", 38.3498, -81.6326),
    ("Columbus, OH", 39.9612, -82.9988),
    ("Cleveland, OH", 41.4993, -81.6944),
    ("Cincinnati, OH", 39.1031, -84.5120),
    ("Toledo, OH", 41.6528, -83.5379),
    ("Dayton, OH", 39.7589, -84.1916),
    ("Detroit, MI", 42.3314, -83.0458),
    ("Grand Rapids, MI", 42.9634, -85.6681),
    ("Lansing, MI", 42.7325, -84.5555),
    ("Indianapolis, IN", 39.7684, -86.1581),
    ("Fort Wayne, IN", 41.0793, -85.1394),
    ("Chicago, IL", 41.8781, -87.6298),
    ("Rockford, IL", 42.2711, -89.0940),
    ("Peoria, IL", 40.6936, -89.5890),
    ("Springfield, IL", 39.7817, -89.6501),
    ("Milwaukee, WI", 43.0389, -87.9065),
    ("Madison, WI", 43.0731, -89.4012),
    ("Green Bay, WI", 44.5133, -88.0133),
    ("Minneapolis, MN", 44.9778, -93.2650),
    ("Duluth, MN", 46.7867, -92.1005),
    ("Des Moines, IA", 41.5868, -93.6250),
    ("Omaha, NE", 41.2565, -95.9345),
    ("Lincoln, NE", 40.8136, -96.7026),
    ("Kansas City, MO", 39.0997, -94.5786),
    ("St. Louis, MO", 38.6270, -90.1994),
    ("Springfield, MO", 37.2089, -93.2923),
    ("Wichita, KS", 37.6872, -97.3301),
    ("Topeka, KS", 39.0473, -95.6752),
    ("Oklahoma City, OK", 35.4676, -97.5164),
    ("Tulsa, OK", 36.1540, -95.9928),
    ("Dallas, TX", 32.7767, -96.7970),
    ("Fort Worth, TX", 32.7555, -97.3308),
    ("Houston, TX", 29.7604, -95.3698),
    ("San Antonio, TX", 29.4241, -98.4936),
    ("Austin, TX", 30.2672, -97.7431),
    ("El Paso, TX", 31.7619, -106.4850),
    ("Lubbock, TX", 33.5779, -101.8552),
    ("Corpus Christi, TX", 27.8006, -97.3964),
    ("Amarillo, TX", 35.2220, -101.8313),
    ("Santa Fe, NM", 35.6870, -105.9378),
    ("Albuquerque, NM", 35.0844, -106.6504),
    ("Denver, CO", 39.7392, -104.9903),
    ("Colorado Springs, CO", 38.8339, -104.8214),
    ("Grand Junction, CO", 39.0639, -108.5506),
    ("Cheyenne, WY", 41.1400, -104.8202),
    ("Billings, MT", 45.7833, -108.5007),
    ("Missoula, MT", 46.8721, -113.9940),
    ("Boise, ID", 43.6150, -116.2023),
    ("Salt Lake City, UT", 40.7608, -111.8910),
    ("Las Vegas, NV", 36.1699, -115.1398),
    ("Reno, NV", 39.5296, -119.8138),
    ("Phoenix, AZ", 33.4484, -112.0740),
    ("Tucson, AZ", 32.2226, -110.9747),
    ("Flagstaff, AZ", 35.1983, -111.6513),
    ("San Diego, CA", 32.7157, -117.1611),
    ("Los Angeles, CA", 34.0522, -118.2437),
    ("Bakersfield, CA", 35.3733, -119.0187),
    ("Fresno, CA", 36.7378, -119.7871),
    ("San Jose, CA", 37.3382, -121.8863),
    ("San Francisco, CA", 37.7749, -122.4194),
    ("Sacramento, CA", 38.5816, -121.4944),
    ("Redding, CA", 40.5865, -122.3917),
    ("Eugene, OR", 44.0521, -123.0868),
    ("Portland, OR", 45.5152, -122.6784),
    ("Seattle, WA", 47.6062, -122.3321),
    ("Spokane, WA", 47.6588, -117.4260),
    ("Anchorage, AK", 61.2181, -149.9003),
    ("Fairbanks, AK", 64.8378, -147.7164),
    ("Honolulu, HI", 21.3069, -157.8583),
    ("Fargo, ND", 46.8772, -96.7898),
    ("Bismarck, ND", 46.8083, -100.7837),
    ("Sioux Falls, SD", 43.5460, -96.7313),
    ("Rapid City, SD", 44.0805, -103.2310),
    ("Toronto, ON", 43.6532, -79.3832),
    ("Ottawa, ON", 45.4215, -75.6972),
    ("Montreal, QC", 45.5017, -73.5673),
    ("Quebec City, QC", 46.8139, -71.2080),
    ("Halifax, NS", 44.6488, -63.5752),
    ("Winnipeg, MB", 49.8951, -97.1384),
    ("Calgary, AB", 51.0447, -114.0719),
    ("Edmonton, AB", 53.5461, -113.4938),
    ("Vancouver, BC", 49.2827, -123.1207),
    ("Mexico City, MX", 19.4326, -99.1332),
    ("Guadalajara, MX", 20.6597, -103.3496),
    ("Monterrey, MX", 25.6866, -100.3161),
    ("Havana, CU", 23.1136, -82.3666),
    ("Kingston, JM", 17.9714, -76.7936),
    ("San Juan, PR", 18.4655, -66.1057),
    ("Panama City, PA", 8.9824, -79.5199),
    ("Bogota, CO", 4.7110, -74.0721),
    ("Lima, PE", -12.0464, -77.0428),
    ("Santiago, CL", -33.4489, -70.6693),
    ("Buenos Aires, AR", -34.6037, -58.3816),
    ("Sao Paulo, BR", -23.5505, -46.6333),
    ("Rio de Janeiro, BR", -22.9068, -43.1729),
    ("Brasilia, BR", -15.7975, -47.8919),
    ("Caracas, VE", 10.4806, -66.9036),
    ("London, GB", 51.5074, -0.1278),
    ("Manchester, GB", 53.4808, -2.2426),
    ("Glasgow, GB", 55.8642, -4.2518),
    ("Dublin, IE", 53.3498, -6.2603),
    ("Paris, FR", 48.8566, 2.3522),
    ("Marseille, FR", 43.2965, 5.3698),
    ("Madrid, ES", 40.4168, -3.7038),
    ("Barcelona, ES", 41.3851, 2.1734),
    ("Lisbon, PT", 38.7223, -9.1393),
    ("Amsterdam, NL", 52.3676, 4.9041),
    ("Brussels, BE", 50.8503, 4.3517),
    ("Berlin, DE", 52.5200, 13.4050),
    ("Munich, DE", 48.1351, 11.5820),
    ("Hamburg, DE", 53.5511, 9.9937),
    ("Zurich, CH", 47.3769, 8.5417),
    ("Vienna, AT", 48.2082, 16.3738),
    ("Prague, CZ", 50.0755, 14.4378),
    ("Warsaw, PL", 52.2297, 21.0122),
    ("Budapest, HU", 47.4979, 19.0402),
    ("Rome, IT", 41.9028, 12.4964),
    ("Milan, IT", 45.4642, 9.1900),
    ("Athens, GR", 37.9838, 23.7275),
    ("Istanbul, TR", 41.0082, 28.9784),
    ("Kyiv, UA", 50.4501, 30.5234),
    ("Stockholm, SE", 59.3293, 18.0686),
    ("Oslo, NO", 59.9139, 10.7522),
    ("Copenhagen, DK", 55.6761, 12.5683),
    ("Helsinki, FI", 60.1699, 24.9384),
    ("Reykjavik, IS", 64.1466, -21.9426),
    ("Moscow, RU", 55.7558, 37.6173),
    ("Cairo, EG", 30.0444, 31.2357),
    ("Lagos, NG", 6.5244, 3.3792),
    ("Nairobi, KE", -1.2921, 36.8219),
    ("Johannesburg, ZA", -26.2041, 28.0473),
    ("Cape Town, ZA", -33.9249, 18.4241),
    ("Casablanca, MA", 33.5731, -7.5898),
    ("Dubai, AE", 25.2048, 55.2708),
    ("Riyadh, SA", 24.7136, 46.6753),
    ("Tel Aviv, IL", 32.0853, 34.7818),
    ("Tehran, IR", 35.6892, 51.3890),
    ("Karachi, PK", 24.8607, 67.0011),
    ("Delhi, IN", 28.6139, 77.2090),
    ("Mumbai, IN", 19.0760, 72.8777),
    ("Bengaluru, IN", 12.9716, 77.5946),
    ("Kolkata, IN", 22.5726, 88.3639),
    ("Dhaka, BD", 23.8103, 90.4125),
    ("Bangkok, TH", 13.7563, 100.5018),
    ("Singapore, SG", 1.3521, 103.8198),
    ("Kuala Lumpur, MY", 3.1390, 101.6869),
    ("Jakarta, ID", -6.2088, 106.8456),
    ("Manila, PH", 14.5995, 120.9842),
    ("Ho Chi Minh City, VN", 10.8231, 106.6297),
    ("Hong Kong, HK", 22.3193, 114.1694),
    ("Shanghai, CN", 31.2304, 121.4737),
    ("Beijing, CN", 39.9042, 116.4074),
    ("Shenzhen, CN", 22.5431, 114.0579),
    ("Seoul, KR", 37.5665, 126.9780),
    ("Tokyo, JP", 35.6762, 139.6503),
    ("Osaka, JP", 34.6937, 135.5023),
    ("Taipei, TW", 25.0330, 121.5654),
    ("Sydney, AU", -33.8688, 151.2093),
    ("Melbourne, AU", -37.8136, 144.9631),
    ("Brisbane, AU", -27.4698, 153.0251),
    ("Perth, AU", -31.9505, 115.8605),
    ("Auckland, NZ", -36.8485, 174.7633),
    ("Wellington, NZ", -41.2866, 174.7756),
)


def nearby_cities(lat: float, lon: float, max_distance: float = 360.0,
                  max_results: int = 6) -> list:
    """
    Find the closest table cities to a point

    Deliberately skips anything sitting almost on top of the home location,
    since a marker stacked under the home marker reads as a rendering fault.

    @param lat: float Latitude in decimal degrees
    @param lon: float Longitude in decimal degrees
    @param max_distance: float How far out to look, in miles
    @param max_results: int How many cities to return
    @return list: Dicts of name, lat, lon, and distance, nearest first
    """

    # nothing wanted
    if max_results <= 0:
        return []

    # measure everything inside the radius
    scored: list = []
    for name, city_lat, city_lon in CITIES:
        distance = haversine_miles(lat, lon, city_lat, city_lon)
        if distance > max_distance or distance < 12.0:
            continue
        scored.append({
            "name": name,
            "lat": city_lat,
            "lon": city_lon,
            "distance": distance,
        })

    # nearest first, trimmed to what was asked for
    scored.sort(key=lambda item: item["distance"])
    return scored[:max_results]


def nearest_city(lat: float, lon: float,
                 max_distance: float = 500.0) -> Optional[str]:
    """
    Name the closest table city to a point

    Used to put a location label on a station configured by raw coordinates.

    @param lat: float Latitude in decimal degrees
    @param lon: float Longitude in decimal degrees
    @param max_distance: float How far out to look, in miles
    @return str|None: The city name, or None when nothing is close enough
    """

    # walk the table keeping the closest
    best_name = None
    best_distance = None
    for name, city_lat, city_lon in CITIES:
        distance = haversine_miles(lat, lon, city_lat, city_lon)
        if best_distance is None or distance < best_distance:
            best_name, best_distance = name, distance

    # only claim it when it is actually nearby
    if best_distance is not None and best_distance <= max_distance:
        return best_name
    return None
