import requests
import json
from datetime import datetime, timezone

# API endpoint
URL = "https://volosports.com/hapi/v1/graphql"

HEADERS = {
    "accept": "application/graphql-response+json,application/json;q=0.9",
    "accept-language": "en-US,en;q=0.9,fr;q=0.8",
    "content-type": "application/json",
    "origin": "https://www.volosports.com",
    "referer": "https://www.volosports.com/",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}

QUERY = """
query DiscoverDaily($where: discover_daily_bool_exp!, $limit: Int = 15, $offset: Int = 0) {
  discover_daily(
    where: $where
    order_by: [{event_start_date: asc}, {event_start_time_str: asc}, {event_end_time_str: asc}, {_id: asc}]
    limit: $limit
    offset: $offset
  ) {
    _id
    game_id
    game {
      _id
      start_time
      end_time
      venueByVenue {
        _id
        shorthand_name
        formatted_address
        neighborhoodByNeighborhoodId {
          _id
          name
          __typename
        }
        __typename
      }
      drop_in_capacity {
        _id
        total_available_spots
        __typename
      }
      leagueByLeague {
        _id
        program_type
        sportBySport {
          _id
          name
          __typename
        }
        __typename
      }
      __typename
    }
    league_id
    league {
      ...LeagueDetails
      __typename
    }
    event_start_date
    event_start_time_str
    event_end_time_str
    __typename
  }
  discover_daily_aggregate(where: $where) {
    aggregate {
      count
      __typename
    }
    __typename
  }
}

fragment LeagueDetails on leagues {
  _id
  name
  display_name
  program_type
  start_date
  is_premier
  is_volo_pass_exclusive
  start_time_estimate
  end_time_estimate
  banner_text
  header
  num_weeks_estimate
  num_playoff_weeks_estimate
  sportBySport {
    _id
    name
    __typename
  }
  registrants_aggregate {
    aggregate {
      count
      __typename
    }
    __typename
  }
  registrationByRegistration {
    _id
    max_registration_size
    min_registration_size
    __typename
  }
  neighborhoodByNeighborhood {
    _id
    name
    __typename
  }
  venueByVenue {
    _id
    shorthand_name
    formatted_address
    __typename
  }
  organizationByOrganization {
    _id
    is_volo_pass_active
    __typename
  }
  __typename
}
"""


def build_payload(
    sports: list[str] = [],
    city: str = "",
    min_male_spots: int = 1,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Build the GraphQL request payload."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    return {
        "operationName": "DiscoverDaily",
        "query": QUERY,
        "variables": {
            "limit": limit,
            "offset": offset,
            "where": {
                "league_id": {"_is_null": True},
                "game_id": {"_is_null": False},
                "game": {
                    "start_time": {"_gte": now_utc},
                    "drop_in_capacity": {
                        "_and": [
                            {"total_male_eligible_spots": {"_gte": min_male_spots}}
                        ]
                    },
                    "leagueByLeague": {
                        "organizationByOrganization": {"name": {"_eq": city}},
                        "sportBySport": {"name": {"_in": sports}},
                    },
                },
            },
        },
        "extensions": {
            "clientLibrary": {"name": "@apollo/client", "version": "4.0.13"}
        },
    }


def fetch_drop_in_games(
    sports: list[str] = ["Soccer"],
    city: str = "Washington DC",
    min_male_spots: int = 1,
    limit: int = 15,
) -> list[dict]:
    """Fetch available drop-in games from the Volo Sports API."""
    payload = build_payload(
        sports=sports, city=city, min_male_spots=min_male_spots, limit=limit
    )

    response = requests.post(URL, headers=HEADERS, json=payload)
    response.raise_for_status()

    data = response.json()
    return data.get("data", {}).get("discover_daily", [])


def format_game(game: dict) -> str:
    """Format a single game entry for display."""
    g = game.get("game", {})
    venue = g.get("venueByVenue", {})
    neighborhood = venue.get("neighborhoodByNeighborhoodId", {})
    capacity = g.get("drop_in_capacity", {})
    sport = g.get("leagueByLeague", {}).get("sportBySport", {}).get("name", "Unknown")

    start_raw = game.get("event_start_date", "")
    start_time_str = game.get("event_start_time_str", "")
    end_time_str = game.get("event_end_time_str", "")

    # Parse and format the date
    try:
        start_dt = datetime.fromisoformat(start_raw)
        date_label = start_dt.strftime("%A, %B %-d, %Y")
    except Exception:
        date_label = start_raw

    spots = capacity.get("total_available_spots", "?")
    venue_name = venue.get("shorthand_name", "Unknown Venue")
    address = venue.get("formatted_address", "")
    neighborhood_name = neighborhood.get("name", "")

    return (
        f"  📅 {date_label}  {start_time_str}–{end_time_str}\n"
        f"  ⚽ {sport}\n"
        f"  📍 {venue_name} ({neighborhood_name})\n"
        f"     {address}\n"
        f"  🟢 {spots} spot(s) available\n"
    )


def main():
    print("🔍 Fetching available drop-in soccer games in Washington DC...\n")

    try:
        games = fetch_drop_in_games(sports=["Soccer"], city="Washington DC")
    except requests.HTTPError as e:
        print(f"❌ HTTP error: {e}")
        return
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return

    if not games:
        print("No drop-in games found.")
        return

    print(f"Found {len(games)} available game(s):\n")
    print("=" * 60)
    for i, game in enumerate(games, start=1):
        print(f"Game #{i}")
        print(format_game(game))
        print("-" * 60)


if __name__ == "__main__":
    main()
