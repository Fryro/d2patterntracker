from flask import Flask, request, render_template, jsonify, redirect, session, url_for, Markup
import json
import requests
import urllib
from urllib.parse import quote, unquote
import os
import sys
import zipfile
import sys
import subprocess
import sqlite3
import pickle
import datetime

app = Flask(__name__)
app.secret_key = "imnotsureifthisneedstobesecuretheresnosensitivedatahere"


hashes = {
    'DestinyInventoryBucketDefinition': 'hash',
    'DestinyInventoryItemDefinition': 'hash',
    'DestinyRecordDefinition': 'hash',
    'DestinyObjectiveDefinition': 'hash'
}


""" 
Major Section - Helper Functions
"""
# This function checks for the local file, "manifest.pickle".
# If it exists, it loads it (hopefully a dictionary representation of the SQLITE manifest)
# If it doesn't, it will make it and return a dictionary representation of the SQLITE manifest (this will always be correct).

# I don't want to do internal comments for this function. So I won't! >:)
def get_manifest(filepath, hash_dict):
    if (not os.path.exists(filepath)):
        manifest_response = requests.get(f"http://www.bungie.net/platform/Destiny2/Manifest/", headers = HEADERS)
        manifest = json.loads((manifest_response.content).decode(manifest_response.encoding))
        for key,value in manifest['Response'].items():
            print(key) 
        manifest_content_en_url = 'http://www.bungie.net'+manifest['Response']['mobileWorldContentPaths']['en']

        db_file = requests.get(manifest_content_en_url)
        with open("MANIFEST-ZIP", "wb") as zipped:
            zipped.write(db_file.content)
        print("Downloaded compressed manifest to 'MANIFEST-ZIP'")

        with zipfile.ZipFile("MANIFEST-ZIP") as zipped:
            name = zipped.namelist()
            zipped.extractall()
        os.rename(name[0], 'manifest.content')
        print("Unzipped namifest to 'manifest.content'")


        con = sqlite3.connect('manifest.content')
        print("Connected to local SQLITE database.")

        cur = con.cursor()

        all_data = {}
        for table_name in hash_dict.keys():
            cur.execute('SELECT json from ' + table_name)
            print("Generating " + table_name + " dictionary...")

            items = cur.fetchall()

            item_jsons = [json.loads(item[0]) for item in items]

            item_dict = {}
            hashed = hash_dict[table_name]
            for item in item_jsons:
                item_dict[item[hashed]] = item

            all_data[table_name] = item_dict
        print("Dictionary Generated.")
        with open(filepath, "wb") as data:
            pickle.dump(all_data, data)
            print(f"Manifest Dictionary placed into '{filepath}'")
        return(all_data)
	
    else:
        with open(filepath, "rb") as data:
            all_data = pickle.load(data)
        return(all_data)



def get_pattern_weapons(manifest, bungie_account):
    # Finally using the rest of the call from earlier. 
    # Get all the records, and set up data structures.
    profile_records = bungie_account['Response']['profileRecords']['data']['records']
    pattern_record_hashes_dict = {}
    pattern_record_hashes = []

    # Iterate over the manifest records (All of them!)
    for key,value in manifest['DestinyRecordDefinition'].items():

        # If the record would unlock a crafting recipe, keep track of it.
        if (value['completionInfo']['toastStyle'] == 8):
            pattern_record_hashes_dict[value['displayProperties']['name']] = key
            pattern_record_hashes.append(key)

    # Set up final data structures, for all weapons and seperately for completed ones.
    all_weapons_and_progress = {}
    weapons_completed = []
    
    # Iterate over all the records that unlock crafting recipes...
    for key,val in pattern_record_hashes_dict.items():
        
        # Get the current record from the user's list of records.
        try:
            profile_record = profile_records[str(val)]
        except:
            print("Hit a snag")
            continue

        # If the record looks like a weapon pattern...
        if (profile_record['objectives'][0]['completionValue']) in [2, 3, 4, 5]:

            # Store all the info on that weapon pattern record that we care about.
            all_weapons_and_progress[key] = {
                "state": profile_record['state'],
                "completed": profile_record['objectives'][0]['complete'],
                "progress": profile_record['objectives'][0]['progress'],
                "completionValue": profile_record['objectives'][0]['completionValue'],
                "hash": val
            }

            # If it's already done, store it seperately in a list.
            if ((profile_record['state'] == 67) and (profile_record['objectives'][0]['progress'] == profile_record['objectives'][0]['completionValue'])):
                weapons_completed.append(f"{key}")
    return(all_weapons_and_progress)





def organize_weapons_by_ammo(manifest, unorganized_weapons):
    organized_weapons_dict = {}
    for key,val in manifest['DestinyInventoryItemDefinition'].items():
        if (val['displayProperties']['name'] in unorganized_weapons.keys()):
            flag = True
            try:
                if (val['itemTypeDisplayName'] not in organized_weapons_dict.keys()):
                    organized_weapons_dict[val['itemTypeDisplayName']] = {}
                   
                organized_weapons_dict[val['itemTypeDisplayName']][val['displayProperties']['name']] = {
                    "itemHash": key,
                    "objectiveHash": unorganized_weapons[val['displayProperties']['name']]['hash'],
                    "state": unorganized_weapons[val['displayProperties']['name']]['state'],
                    "completed": unorganized_weapons[val['displayProperties']['name']]['completed'],
                    "progress": unorganized_weapons[val['displayProperties']['name']]['progress'],
                    "completionValue": unorganized_weapons[val['displayProperties']['name']]['completionValue'],
                    "icon-url": ("http://www.bungie.net/" + val['displayProperties']['icon']),
                    "screenshot-url": ("http://www.bungie.net/" + val['screenshot'])
                }
            except Exception as e:
                organized_weapons_dict[val['itemTypeDisplayName']][val['displayProperties']['name']] = {
                    "itemHash": key,
                    "objectiveHash": unorganized_weapons[val['displayProperties']['name']]['hash'],
                    "state": unorganized_weapons[val['displayProperties']['name']]['state'],
                    "completed": unorganized_weapons[val['displayProperties']['name']]['completed'],
                    "progress": unorganized_weapons[val['displayProperties']['name']]['progress'],
                    "completionValue": unorganized_weapons[val['displayProperties']['name']]['completionValue'],
                    "icon-url": ("http://www.bungie.net/" + val['displayProperties']['icon']),
                    "screenshot-url": ("N/A")
                }
                flag = True
    return(organized_weapons_dict)




"""
MAJOR SECTION
Driving Code (Entrypoint)
"""
# This section attempts to open a json file, which contains API secrets.
# If it cannot, 'j' remains 'None' and the program will exit.
debug = False
j = None
try:
    with open("./bungieapi.json", "r") as f:
        j = json.load(f)
except Exception as e:
    if (debug):
        print(str(e))
        sys.exit("Fatal Error: could not resolved json.")

if not (j):
    sys.exit("Fatal Error: could not resolved json.")

# Set headers based on 'j'.
HEADERS = {
    "X-API-Key": j['api_key']
}
# This is a set value, used for certain API calls. This correlates to account type "BungieNext".
membership_type = 254

def get_user(account_query):

    # Start a search at page 0. There is an option appended to the list of users that will
    #   load the next page of results, should there be more than one page.
    page = 0

    # This is the POST that gets a page of result users.
    account_search_response = requests.post(f"https://www.bungie.net/Platform/User/Search/GlobalName/0/", headers = HEADERS, data=json.dumps({"displayNamePrefix": f"{account_query}"}))

    # If that didn't work, go ahead and return (None, None).
    if (account_search_response.status_code != 200):
        sys.exit("Fatal Error: Could not hit Bungie API (GlobalNameSearch")

    # Try to load the returned structure as a dictionary. If it doesn't work, return (None, None).
    try:
        account_search = json.loads((account_search_response.content).decode(account_search_response.encoding))['Response']

        # Initialize a dictionary to hold accounts that have destiny info attached.
        accounts_found = {}

        # Iterate over all accounts on the page.
        for result in account_search['searchResults']:
            ### NOTE!! There can technically be more than one destiny account per bungie account.
            ### NOTE!! I'm just choosing to index 0 here, so I'm assuming the first is correct.
            # This block is here to catch situations where the user has no destiny info.
            try:
                # A long a gross line that just filters and stores information we care about.
                accounts_found["{}#{}".format(str(result['bungieGlobalDisplayName']), str(result['bungieGlobalDisplayNameCode']))] = {
            "destinyMembershipId": result['destinyMemberships'][0]['membershipId'],
            "applicableMembershipTypes": result['destinyMemberships'][0]['applicableMembershipTypes']
            }
            except Exception as e:
                continue
    except Exception as e:
        print(str(e))
        return((None, None))

    return(accounts_found)


def get_bungie_account(membership_types, destiny_id):
    # This querystring(_int) is used in the next API call. Both of these can be passed in.
    # This controls what information we get back from the API call.
    #querystring = "Profiles,Characters,CharacterRenderData,CharacterEquipment,CharacterLoadouts,Records,Craftables"
    #querystring_int = "100,200,203,205,206,900,1300"
    querystring = "Profiles,Records"

    # For some reason, only the last entry works. I don't know why.
    selected_membership_type = membership_types[-1]
    selected_destiny_id = destiny_id
    bungie_account_response = requests.get(f"http://www.bungie.net/Platform/Destiny2/{selected_membership_type}/Profile/{selected_destiny_id}/?components={querystring}", headers = HEADERS)

    # If that .get didn't work, go ahead and exit. We can't proceed without that information.
    if (bungie_account_response.status_code != 200):
        print(f"Response from bungie was not 200:\n\t{bungie_account_response.status_code}\n\t{bungie_account_response.content}")
        sys.exit("Fatal Error: Could not not retrieve Profile endpoint.")

    # If it DID work, decode and retrieve the information as a dictionary.
    bungie_account = json.loads((bungie_account_response.content).decode(bungie_account_response.encoding))
    return(bungie_account)







@app.route("/")
def index():
    querystring_raw = request.query_string
    if (len(querystring_raw) > 0):
        #print(querystring)
        querystring = unquote(querystring_raw[5:]).replace('+', ' ')[0:-5] #unquote(querystring[5:])
        username = unquote(querystring_raw[5:]).replace('+', ' ')
        #querystring = unquote(querystring[5:])[0:-5] #unquote(querystring[5:])
        #return redirect(f"/patterntracker/{querystring}/", code = 200)
        accounts_found = get_user(querystring)
        for key,value in accounts_found.items():
            if str(key) == (username):
                user_info = {
                    "username": username,
                    "applicableMembershipTypes": value["applicableMembershipTypes"],
                    "destinyMembershipId": value["destinyMembershipId"]
                }#get_bungie_account(value["applicableMembershipTypes"], value["destinyMembershipId"])
                session['user_info'] = user_info
                filepath = str(username)
                bungie_account = get_bungie_account(user_info["applicableMembershipTypes"], user_info["destinyMembershipId"])
                session['filepath'] = f"./pickles/{filepath}.pickle"
                with open(session['filepath'], 'wb') as file:
                    pickle.dump(bungie_account, file)
                return redirect(url_for(".get_patterns"), code = 200)

                #return (f"{key}: {value}")
            else:
                continue
        return ("Account Not Found")
    currenttime = datetime.datetime.now()
    return render_template("index.html", currenttime = currenttime)



@app.route("/patterntracker/")
def get_patterns():
    user_info = session['user_info']
    with open(session['filepath'], 'rb') as file:
        bungie_account = pickle.load(file)#get_bungie_account(user_info["applicableMembershipTypes"], user_info["destinyMembershipId"])
    manifest = get_manifest("manifest.pickle", hashes)
    
    pattern_weapons_by_type = organize_weapons_by_ammo(manifest, get_pattern_weapons(manifest, bungie_account))
    del pattern_weapons_by_type[""]
    
    """
    display_str = f"Pattern Weapons for {user_info['username']}<br>========================================<br>"
    for weapon_type,weapons in pattern_weapons_by_type.items():
        if (weapon_type == ""):
            continue
        display_str += "----------------------------------------<br>"
        display_str += f"<<< {weapon_type} >>> <br>"
        display_str += "----------------------------------------<br>"
        for weapon,patterninfo in weapons.items():
            if (patterninfo["completed"]):
                display_str += " COMPLETED "
            else:
                display_str += " NOT COMPLETED "
            display_str += f"{weapon}  Patterns: [{patterninfo['progress']}/{patterninfo['completionValue']}]<br>"
    """
    
    pwd = {}
    for weapon_type,weapons in pattern_weapons_by_type.items():
        pwd[str(weapon_type)] = {}
        for weapon_name,weapon_info in weapons.items():
            pwd[str(weapon_type)][str(weapon_name)] = {key:weapon_info[key] for key in ['icon-url', 'completionValue', 'progress']}
            pwd[str(weapon_type)][str(weapon_name)]['name'] = str(weapon_name) 
            pwd[str(weapon_type)][str(weapon_name)]['icon'] = pwd[str(weapon_type)][str(weapon_name)].pop('icon-url')  
            pwd[str(weapon_type)][str(weapon_name)]['percentage'] = round((weapon_info['progress'] / weapon_info['completionValue']) * 100)
             
    currenttime = datetime.datetime.now()
    return render_template("patterntracker.html", pwd=pwd)#pattern_weapons_by_type) 
    #return (display_str)
    
@app.route("/search/<string:box>")
def process(box):
    query = request.args.get('query')
    if box == 'names':
        suggestions = []
        accounts_query = get_user(query)
        for user,userinfo in accounts_query.items():
            suggestions.append({'value': user, 'data': user})
    return jsonify({"suggestions":suggestions})

if __name__ == "__main__":
    app.run(debug=True)
