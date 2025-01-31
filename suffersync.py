import requests
import json
import re
import os
import sys
from datetime import datetime
from dateutil import tz
from base64 import b64encode

########################################################################################################
# Change these to your own Wahoo SYSTM credentials & intervals.icu                                     #
# Setup the dates you want to get the workouts for, only future workouts will be sent to intervals.icu #
########################################################################################################
SYSTM_USERNAME = 'your_systm_username'
SYSTM_PASSWORD = 'your_systm_password'
START_DATE = "2021-11-01T00:00:00.000Z"
END_DATE = "2021-12-31T23:59:59.999Z"
INTERVALS_ICU_ID = "i00000"
INTERVALS_ICU_APIKEY = "xxxxxxxxxxxxx"
# Change this to 1 if you want to upload yoga workouts to intervals.icu
UPLOAD_YOGA_WORKOUTS = 0
# Change this to 1 if you want to upload past SYSTM workouts to intervals.icu
UPLOAD_PAST_WORKOUTS = 0


# Don't change anything below this line
def get_systm_token(url, username, password):
    payload = json.dumps({
        "operationName": "Login",
        "variables": {
            "appInformation": {
                "platform": "web",
                "version": "7.12.0-web.2141",
                "installId": "F215B34567B35AC815329A53A2B696E5"
            },
            "username": username,
            "password": password
        },
        "query": "mutation Login($appInformation: AppInformation!, $username: String!, $password: String!) { loginUser(appInformation: $appInformation, username: $username, password: $password) { status message user { ...User_fragment __typename } token failureId __typename }}fragment User_fragment on User { id fullName firstName lastName email gender birthday weightKg heightCm createdAt metric emailSharingOn legacyThresholdPower wahooId wheelSize { name id __typename } updatedAt profiles { riderProfile { ...UserProfile_fragment __typename } __typename } connectedServices { name __typename } timeZone onboardingProgress { complete completedSteps __typename } subscription { validUntil trialAvailable __typename } avatar { url original { url __typename } square200x200 { url __typename } square256x256 { url __typename } thumb { url __typename } __typename } onboardingComplete createdWithAppInformation { version platform __typename } __typename}fragment UserProfile_fragment on UserProfile { nm ac map ftp lthr cadenceThreshold riderTypeInfo { name icon iconSmall systmIcon description __typename } riderWeaknessInfo { name __typename } recommended { nm { value activity __typename } ac { value activity __typename } map { value activity __typename } ftp { value activity __typename } __typename } __typename}"
    })

    headers = {'Content-Type': 'application/json'}

    response = call_api(url, headers, payload)
    response_json = response.json()
    token = response_json['data']['loginUser']['token']
    return token


def get_systm_workouts(url, token, start_date, end_date):
    payload = json.dumps({
        "operationName": "GetUserPlansRange",
        "variables": {
            "startDate": start_date,
            "endDate": end_date,
            "queryParams": {
                "limit": 1000
            }
        },
        "query": "query GetUserPlansRange($startDate: Date, $endDate: Date, $queryParams: QueryParams) { userPlan(startDate: $startDate, endDate: $endDate, queryParams: $queryParams) { ...UserPlanItem_fragment __typename }}fragment UserPlanItem_fragment on UserPlanItem { day plannedDate rank agendaId status type appliedTimeZone completionData { name date activityId durationSeconds style deleted __typename } prospects { type name compatibility description style intensity { master nm ac map ftp __typename } trainerSetting { mode level __typename } plannedDuration durationType metrics { ratings { nm ac map ftp __typename } __typename } contentId workoutId notes fourDPWorkoutGraph { time value type __typename } __typename } plan { id name color deleted durationDays startDate endDate addons level subcategory weakness description category grouping option uniqueToPlan type progression planDescription volume __typename } __typename}"
    })

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    # Get workouts from Wahoo SYSTM plan
    response = call_api(url, headers, payload).json()
    return response


def get_systm_workout(url, token, workout_id):
    payload = json.dumps({
        "operationName": "GetWorkouts",
        "variables": {
            "id": workout_id
        },
        "query": "query GetWorkouts($id: ID) {workouts(id: $id) { id sortOrder sport stampImage bannerImage bestFor equipment { name description thumbnail __typename } details shortDescription level durationSeconds name triggers featuredRaces { name thumbnail darkBackgroundThumbnail __typename } metrics { intensityFactor tss ratings { nm ac map ftp __typename } __typename } brand nonAppWorkout notes tags imperatives { userSettings { birthday gender weight __typename } __typename } __typename}}"
    })

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    response = call_api(url, headers, payload).text
    return response


def upload_to_intervals_icu(date, filename, contents):
    url = f'https://intervals.icu/api/v1/athlete/{INTERVALS_ICU_ID}/events'

    payload = json.dumps({
        "category": "WORKOUT",
        "start_date_local": date,
        "type": "Ride",
        "filename": filename,
        "file_contents": contents
    })

    token = b64encode(f'API_KEY:{INTERVALS_ICU_APIKEY}'.encode()).decode()
    headers = {
        'Authorization': f'Basic {token}',
        'Content-Type': 'text/plain'
    }

    response = call_api(url, headers, payload)
    return response


def call_api(url, headers, payload):
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
    except Exception as err:
        raise(err)
    return response


def clean_workout(workout):
    # Remove the details section, too many string errors.
    regex = r"(\"details.*?)(?=\"l)"
    workout = re.sub(regex, "", workout, 0, re.MULTILINE)
    # Remove '\\\"' in the trigger section
    workout = workout.replace("\\\\\\\"", "")
    # Remove the '\\', mostly seen in the trigger section
    workout = workout.replace("\\", "")
    # Make sure that the 'triggers' section is JSON compliant, remove the " at the start and end.
    workout = workout.replace('"triggers":"', '"triggers":')
    workout = workout.replace('","featuredRaces"', ',"featuredRaces"')
    return workout


def main():
    SYSTM_URL = "https://api.thesufferfest.com/graphql"

    # Get Wahoo SYSTM auth token
    systm_token = get_systm_token(SYSTM_URL, SYSTM_USERNAME, SYSTM_PASSWORD)

    # Get Wahoo SYSTM workouts from training plan
    workouts = get_systm_workouts(SYSTM_URL, systm_token, START_DATE, END_DATE)

    # Even with errors, response.status_code comes back as 200 so catching errors this way.
    if 'errors' in workouts:
        print(f'Wahoo SYSTM Error: {workouts["errors"][0]["message"]}')
        sys.exit(1)

    workouts = workouts['data']['userPlan']

    # For each workout, make sure there's a "plannedDate" field to avoid bogus entries.
    for item in workouts:
        if item['plannedDate']:
            # Get plannedDate, convert to UTC DateTime and then to local timezone
            planned_date = item['plannedDate']
            dt_planned_date = datetime.strptime(planned_date, "%Y-%m-%dT%H:%M:%S.%fZ")
            timezone = tz.gettz(item['appliedTimeZone'])
            dt_workout_date_utc = dt_planned_date.replace(tzinfo=tz.gettz('UTC'))
            dt_workout_date_local = dt_workout_date_utc.astimezone(timezone)
            dt_workout_date_short = dt_workout_date_local.strftime("%Y-%m-%d")

            # Get workout name and remove invalid characters to avoid filename issues.
            workout_name = item['prospects'][0]['name']
            workout_name = re.sub("[:]", "", workout_name)
            workout_name = re.sub("[ ,./]", "_", workout_name)
            filename = f'{dt_workout_date_short}_{workout_name}'

            try:
                workout_id = item['prospects'][0]['workoutId']
            except Exception as err:
                print(f'Error: {err}')

            # Get specific workout
            workout_detail = get_systm_workout(SYSTM_URL, systm_token, workout_id)

            # Create .zwo files with workout details
            filename_zwo = f'./zwo/{filename}.zwo'
            os.makedirs(os.path.dirname(filename_zwo), exist_ok=True)

            try:
                # Workout details are not clean JSON, so use clean_workout() before loading as JSON
                workout_detail = clean_workout(workout_detail)
                workout_json = json.loads(workout_detail)
                sport = workout_json['data']['workouts'][0]['sport']

                # Skip yoga workouts if UPLOAD_YOGA_WORKOUTS = 0
                if sport == 'Yoga' and not UPLOAD_YOGA_WORKOUTS:
                    continue

                # 'triggers' contains the FTP values for the workout
                workout_json = workout_json['data']['workouts'][0]['triggers']

                f = open(filename_zwo, "a")
                if not workout_json:
                    f.write('No workout data found.')
                    f.close()
                else:
                    text = r"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workout_file>
    <author></author>
    <name></name>
    <description></description>
    <sportType>bike</sportType>
    <tags/>
    <workout>"""
                    f.write(text)

                    for interval in range(len(workout_json)):
                        for tracks in range(len(workout_json[interval]['tracks'])):
                            for item in workout_json[interval]['tracks'][tracks]['objects']:
                                seconds = int(item['size'] / 1000)
                                if 'ftp' in item['parameters']:
                                    ftp = item['parameters']['ftp']['value']
                                    if 'rpm' in item['parameters']:
                                        rpm = item['parameters']['rpm']['value']
                                        text = f'\n\t\t<SteadyState show_avg="1" Cadence="{rpm}" Power="{ftp}" Duration="{seconds}"/>'
                                    else:
                                        text = f'\n\t\t<SteadyState show_avg="1" Power="{ftp}" Duration="{seconds}"/>'
                                    f.write(text)
                    text = r"""
    </workout>
</workout_file>"""
                    f.write(text)

            except Exception as err:
                print(f'{err}')

            f.close()

            try:
                today = datetime.today()
                zwo_file = open(filename_zwo, 'r')
                date = filename_zwo[6:16]
                file_date = f'{date}T00:00:00'
                date = datetime.strptime(date, "%Y-%m-%d")
                intervals_filename = f'{filename_zwo[17:]}'
                file_contents = zwo_file.read()

                if date > today or UPLOAD_PAST_WORKOUTS:
                    response = upload_to_intervals_icu(file_date, intervals_filename, file_contents)
                    if response.status_code == 200:
                        print(f'Uploaded {intervals_filename}')

                zwo_file.close()
            except Exception as err:
                print(f'Something went wrong with {intervals_filename}: {err}')


if __name__ == "__main__":
    main()
