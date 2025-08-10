import json

def extract_showtimes(json_data, target_date):
    results = []
    
    show_dates = json_data.get("showtimesByEvent", {}).get("showDates", {})
    date_obj = show_dates.get(target_date, {})
    widgets = date_obj.get("dynamic", {}).get("data", {}).get("showtimeWidgets", [])
    
    for widget in widgets:
        if widget.get("type") == "groupList" and widget.get("id") == "List_1":
            for group in widget.get("data", []):
                if group.get("type") == "venueGroup" and group.get("id") == "Venue_GROUP_1":
                    for venue in group.get("data", []):
                        if venue.get("type") == "venue-card":
                            vdata = venue.get("additionalData", {})
                            venue_name = vdata.get("venueName")
                            venue_code = vdata.get("venueCode")
                            
                            theatre_info = {
                                "venueName": venue_name,
                                "venueCode": venue_code,
                                "shows": []
                            }
                            
                            # Extract all showtimes
                            for show in venue.get("showtimes", []):
                                show_time = show.get("title") or show.get("showTime")
                                session_id = show.get("additionalData", {}).get("sessionId")
                                categories = []
                                for cat in show.get("additionalData", {}).get("categories", []):
                                    categories.append({
                                        "seatType": cat.get("priceDesc"),
                                        "price": cat.get("curPrice")
                                    })
                                
                                theatre_info["shows"].append({
                                    "time": show_time,
                                    "sessionId": session_id,
                                    "categories": categories
                                })

                            results.append(theatre_info)
    return results


if __name__ == "__main__":
    with open("dhadak2.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    extracted = extract_showtimes(data, "20250810")
    
    # Save the extracted data as JSON
    with open("extracted_showtimes.json", "w", encoding="utf-8") as out_file:
        json.dump(extracted, out_file, indent=4, ensure_ascii=False)
    
    # Also print JSON to console
    print(json.dumps(extracted, indent=4, ensure_ascii=False))