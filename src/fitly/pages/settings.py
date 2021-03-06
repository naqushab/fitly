import dash
import dash_html_components as html
from dash.dependencies import Input, Output, State
import dash_core_components as dcc
import dash_bootstrap_components as dbc
import dash_daq as daq
from oura import OuraOAuth2Client
from ..api.ouraAPI import oura_connected, connect_oura_link, save_oura_token
from ..api.stravaApi import strava_connected, get_strava_client, connect_strava_link, save_strava_token
from ..api.withingsAPI import withings_connected, connect_withings_link, save_withings_token
from ..api.pelotonApi import get_class_types
from nokia import NokiaAuth, NokiaApi
from ..api.sqlalchemy_declarative import db_connect, stravaSummary, ouraSleepSummary, athlete, hrvWorkoutStepLog
from ..api.datapull import refresh_database
from sqlalchemy import delete
import pandas as pd
from dateutil.relativedelta import relativedelta
from datetime import datetime
from ..api.fitlyAPI import hrv_training_workflow
from ..app import app
from flask import current_app as server
import re
from ..utils import peloton_credentials_supplied, oura_credentials_supplied, withings_credentials_supplied, config
import json
import ast

strava_auth_client = get_strava_client()
withings_auth_client = NokiaAuth(config.get('withings', 'client_id'), config.get('withings', 'client_secret'),
                                 callback_uri=config.get('withings', 'redirect_uri'))
oura_auth_client = OuraOAuth2Client(client_id=config.get('oura', 'client_id'),
                                    client_secret=config.get('oura', 'client_secret'))


def get_layout(**kwargs):
    return html.Div([
        html.Div(id='settings-layout'),
        html.Div(id='clear-log-dummy', style={'display': 'none'}),
        html.Div(id='token-dummy', style={'display': 'none'}),
        html.Div(id='peloton-dummy', style={'display': 'none'}),
        dbc.Modal(id="settings-modal", centered=True, autoFocus=True, fade=False, backdrop=True, size='sm',
                  is_open=True,
                  children=[
                      dbc.ModalHeader("Enter Admin Password"),
                      dbc.ModalBody(className='align-items-center text-center', children=[
                          dbc.Input(id='settings-password', type='password', placeholder='Password', bs_size="sm",
                                    value='')]),
                      dbc.ModalFooter(html.Div([
                          dcc.Link(
                              dbc.Button("Close", id='close-button', n_clicks=0, className='mr-2', color='secondary',
                                         size='sm'),
                              href='/home'),
                          dbc.Button("Submit", id="submit-settings-button", n_clicks=0, color='primary', size='sm')
                      ])),
                  ])
    ])


def check_oura_connection():
    if oura_credentials_supplied:
        # If not connected, send to auth app page to start token request
        if not oura_connected():
            return html.A(className='col-lg-12', children=[
                dbc.Button('Connect Oura', id='connect-oura-button', color='primary', className='mb-2',
                           size='md')],
                          href=connect_oura_link(oura_auth_client))
        else:
            return html.H4('Oura Connected!', className='col-lg-12', )
    else:
        return html.Div()


def check_strava_connection():
    # If not connected, send to auth app page to start token request
    if not strava_connected():
        return html.A(className='col-lg-12', children=[
            dbc.Button('Connect Strava', id='connect-strava-button', color='primary', className='mb-2',
                       size='md')],
                      href=connect_strava_link(get_strava_client()))
    else:
        return html.H4('Strava Connected!', className='col-lg-12', )


def check_withings_connection():
    if withings_credentials_supplied:
        # If not connected, send to auth app page to start token request
        if not withings_connected():
            return html.A(className='col-lg-12', children=[
                dbc.Button('Connect Withings', id='connect-withings-btton', color='primary',
                           className='mb-2',
                           size='md')],
                          href=connect_withings_link(
                              NokiaAuth(config.get('withings', 'client_id'), config.get('withings', 'client_secret'),
                                        callback_uri=config.get('withings', 'redirect_uri'))))
        else:
            return html.H4('Withings Connected!', className='col-lg-12', )
    else:
        return html.Div()


def generate_cycle_power_zone_card():
    # TODO: Switch over to using Critical Power for everything once we get the critical power model working
    session, engine = db_connect()
    # Use last ftp test ride so power zones shows immideately here after workout is done (and you don't have to wait for 1 more since ftp doesnt take 'effect' until ride after ftp test)
    cftp = pd.read_sql(
        sql=session.query(stravaSummary.average_watts).filter(stravaSummary.type.like('ride'),
                                                              stravaSummary.name.like('%ftp test%')).statement,
        con=engine)
    cftp = round(int(cftp.loc[cftp.index.max()].fillna(0)['average_watts']) * .95) if len(cftp) > 0 else 0
    athlete_info = session.query(athlete).filter(athlete.athlete_id == 1).first()

    engine.dispose()
    session.close()

    cycle_power_zone_threshold_1 = athlete_info.cycle_power_zone_threshold_1
    cycle_power_zone_threshold_2 = athlete_info.cycle_power_zone_threshold_2
    cycle_power_zone_threshold_3 = athlete_info.cycle_power_zone_threshold_3
    cycle_power_zone_threshold_4 = athlete_info.cycle_power_zone_threshold_4
    cycle_power_zone_threshold_5 = athlete_info.cycle_power_zone_threshold_5
    cycle_power_zone_threshold_6 = athlete_info.cycle_power_zone_threshold_6

    return dbc.Card([
        dbc.CardHeader(html.H4(className='text-left', children='Cycling Power Zones')),
        dbc.CardBody([
            html.H5('Cycling FTP: {}'.format(cftp)),
            generate_db_setting('cycle-zone1', 'Z1: <= {:.0f}'.format((cftp * cycle_power_zone_threshold_1)),
                                cycle_power_zone_threshold_1),
            generate_db_setting('cycle-zone2',
                                'Z2: {:.0f} - {:.0f}'.format((cftp * cycle_power_zone_threshold_1) + 1,
                                                             cftp * cycle_power_zone_threshold_2),
                                cycle_power_zone_threshold_2),
            generate_db_setting('cycle-zone3',
                                'Z3: {:.0f} - {:.0f}'.format((cftp * cycle_power_zone_threshold_2) + 1,
                                                             cftp * cycle_power_zone_threshold_3),
                                cycle_power_zone_threshold_3),
            generate_db_setting('cycle-zone4',
                                'Z4: {:.0f} - {:.0f}'.format((cftp * cycle_power_zone_threshold_3) + 1,
                                                             cftp * cycle_power_zone_threshold_4),
                                cycle_power_zone_threshold_4),
            generate_db_setting('cycle-zone5',
                                'Z5: {:.0f} - {:.0f}'.format((cftp * cycle_power_zone_threshold_4) + 1,
                                                             cftp * cycle_power_zone_threshold_5),
                                cycle_power_zone_threshold_5),
            generate_db_setting('cycle-zone6',
                                'Z6: {:.0f} - {:.0f}'.format((cftp * cycle_power_zone_threshold_5) + 1,
                                                             cftp * cycle_power_zone_threshold_6),
                                cycle_power_zone_threshold_6),
            html.H6('Z7: >= {:.0f}'.format((cftp * cycle_power_zone_threshold_6) + 1),
                    className='col-5 mb-0'),
        ])
    ])

    # html.Div(className='col', children=[
    #     generate_goal(id='ftp-test-notification-threshold', title='FTP Retest Notification (weeks)',
    #                   value=athlete_info.ftp_test_notification_week_threshold),
    # ]),


def generate_run_power_zone_card():
    # TODO: Switch over to using Critical Power for everything once we get the critical power model working
    session, engine = db_connect()
    rftp = pd.read_sql(
        sql=session.query(stravaSummary.ftp).filter(stravaSummary.type.like('run')).statement, con=engine)
    rftp = int(rftp.loc[rftp.index.max()].fillna(0)['ftp']) if len(rftp) > 0 else 0
    athlete_info = session.query(athlete).filter(athlete.athlete_id == 1).first()

    engine.dispose()
    session.close()

    run_power_zone_threshold_1 = athlete_info.run_power_zone_threshold_1
    run_power_zone_threshold_2 = athlete_info.run_power_zone_threshold_2
    run_power_zone_threshold_3 = athlete_info.run_power_zone_threshold_3
    run_power_zone_threshold_4 = athlete_info.run_power_zone_threshold_4

    return dbc.Card([
        dbc.CardHeader(html.H4(className='text-left', children='Running Power Zones')),
        dbc.CardBody([
            html.H5('Running FTP: {}'.format(rftp)),

            generate_db_setting('run-zone1', 'Z1: <= {:.0f}'.format((rftp * run_power_zone_threshold_1)),
                                run_power_zone_threshold_1),
            generate_db_setting('run-zone2',
                                'Z2: {:.0f} - {:.0f}'.format((rftp * run_power_zone_threshold_1) + 1,
                                                             rftp * run_power_zone_threshold_2),
                                run_power_zone_threshold_2),
            generate_db_setting('run-zone3',
                                'Z3: {:.0f} - {:.0f}'.format((rftp * run_power_zone_threshold_2) + 1,
                                                             rftp * run_power_zone_threshold_3),
                                run_power_zone_threshold_3),
            generate_db_setting('run-zone4',
                                'Z4: {:.0f} - {:.0f}'.format((rftp * run_power_zone_threshold_3) + 1,
                                                             rftp * run_power_zone_threshold_4),
                                run_power_zone_threshold_4),
            html.H6('Z5: >= {:.0f}'.format((rftp * run_power_zone_threshold_4) + 1),
                    className='col-5 mb-0')
        ])
    ])


def athlete_card():
    session, engine = db_connect()
    athlete_info = session.query(athlete).filter(athlete.athlete_id == 1).first()
    engine.dispose()
    session.close()
    color = '' if athlete_info.name and athlete_info.birthday and athlete_info.sex and athlete_info.weight_lbs and athlete_info.resting_hr and athlete_info.run_ftp and athlete_info.ride_ftp else 'border-danger'
    peloton_class_types = get_class_types()

    if peloton_credentials_supplied:
        peloton_bookmark_settings = html.Div(
            children=[html.H5('Peloton HRV Recommendation Auto Bookmarking', className='col-12 mb-2 mt-2'),
                      html.Div(className='row mb-2 mt-2', children=[
                          html.Div(className='col-lg-6', children=[
                              dcc.Dropdown(
                                  id='peloton-bookmark-fitness-discipline-dropdown',
                                  placeholder="Fitness Discipline",
                                  options=[
                                      {'label': f'{x.capitalize()}', 'value': f'{x}'} for x in
                                      peloton_class_types.keys()],
                                  multi=False
                              )
                          ]),
                          html.Div(className='col-lg-6', children=[
                              dcc.Dropdown(
                                  id='peloton-bookmark-effort-dropdown',
                                  placeholder="HRV Effort Rec.",
                                  options=[
                                      {'label': 'Rest', 'value': 'Rest'},
                                      {'label': 'Low', 'value': 'Low'},
                                      {'label': 'Mod', 'value': 'Mod'},
                                      {'label': 'HIIT', 'value': 'HIIT'},
                                      {'label': 'High', 'value': 'High'}
                                  ],
                                  multi=False
                              )
                          ]),
                      ]),
                      html.Div(className='row mb-2 mt-2', children=[
                          html.Div(className='col-lg-12', children=[
                              dcc.Dropdown(
                                  id='peloton-bookmark-class-type-dropdown',
                                  placeholder="Select Fitness Discipline & HRV Effort Rec",
                                  multi=True
                              )
                          ])
                      ]),
                      html.Div(className='row mb-2 mt-2 text-center', children=[
                          html.Div(className='col-5'),
                          # dbc.Button("Save", id='peloton-save-button', n_clicks=0, className='text-center col-2',
                          #            color='secondary',
                          #            size='sm'),
                          html.Button(id='peloton-bookmark-input-submit', className='col-2 fa fa-upload',
                                      style={'display': 'inline-block', 'border': '0px'}),

                          html.I(id='peloton-bookmark-input-status', className='col-2 fa fa-check',
                                 style={'display': 'inline-block', 'color': 'rgba(0,0,0,0)',
                                        'fontSize': '150%'}),
                          html.Div(className='col-1'),
                      ])
                      ])
    else:
        peloton_bookmark_settings = html.Div()

    return dbc.Card(id='athlete-card', className=color, children=[
        dbc.CardHeader(html.H4(className='text-left', children='Athlete')),
        dbc.CardBody([
            generate_db_setting('name', 'Name', athlete_info.name),
            generate_db_setting('birthday', 'Birthday (YYYY-MM-DD)', athlete_info.birthday),
            generate_db_setting('sex', 'Sex (M/F)', athlete_info.sex),
            generate_db_setting('weight', 'Weight (lbs)', athlete_info.weight_lbs),
            generate_db_setting('rest-hr', 'Resting HR', athlete_info.resting_hr),
            generate_db_setting('ride-ftp', 'Ride FTP', athlete_info.ride_ftp),
            generate_db_setting('run-ftp', 'Run FTP', athlete_info.run_ftp),
            peloton_bookmark_settings

        ])
    ])


def generate_hr_zone_card():
    session, engine = db_connect()
    rhr = pd.read_sql(
        sql=session.query(ouraSleepSummary.hr_lowest).statement,
        con=engine)
    rhr = int(rhr.loc[rhr.index.max()]['hr_lowest']) if len(rhr) > 0 else 0
    athlete_info = session.query(athlete).filter(athlete.athlete_id == 1).first()
    birthday = athlete_info.birthday

    engine.dispose()
    session.close()

    age = relativedelta(datetime.today(), birthday).years
    max_hr = 220 - age
    hrr = max_hr - rhr

    hr_zone_threshold_1 = athlete_info.hr_zone_threshold_1
    hr_zone_threshold_2 = athlete_info.hr_zone_threshold_2
    hr_zone_threshold_3 = athlete_info.hr_zone_threshold_3
    hr_zone_threshold_4 = athlete_info.hr_zone_threshold_4

    z1 = round((hrr * hr_zone_threshold_1) + rhr)
    z2 = round((hrr * hr_zone_threshold_2) + rhr)
    z3 = round((hrr * hr_zone_threshold_3) + rhr)
    z4 = round((hrr * hr_zone_threshold_4) + rhr)

    return dbc.Card([
        dbc.CardHeader(html.H4(className='text-left', children='Heart Rate Zones')),
        dbc.CardBody([
            html.H5('Based of Resting Heart Rate: {}'.format(rhr)),
            generate_db_setting('hr-zone1', 'Z1: <= {:.0f}'.format(z1), hr_zone_threshold_1),
            generate_db_setting('hr-zone2', 'Z2 : {:.0f} - {:.0f}'.format(z1 + 1, z2), hr_zone_threshold_2),
            generate_db_setting('hr-zone3', 'Z3: {:.0f} - {:.0f}'.format(z2 + 1, z3), hr_zone_threshold_3),
            generate_db_setting('hr-zone4', 'Z4: {:.0f} - {:.0f}'.format(z3 + 1, z4), hr_zone_threshold_4),
            html.H6('Z5: >= {:.0f}'.format(z4 + 1), className='col-5 mb-0')

        ])
    ])


def generate_db_setting(id, title, value, placeholder=None):
    return (
        # html.Div(id=id, className='row mb-2 mt-2', children=[
        html.Div(id=id, className='row align-items-center mb-2 mt-2', children=[
            html.H6(title, className='col-5 mb-0'),
            dbc.Input(id=id + '-input', className='text-center col-5', type='text', bs_size="sm", value=value,
                      placeholder=placeholder),
            html.Button(id=id + '-input-submit', className='col-2 fa fa-upload',
                        style={'display': 'inline-block', 'border': '0px'}),

            html.I(id=id + '-input-status', className='col-2 fa fa-check',
                   style={'display': 'none', 'color': 'rgba(0,0,0,0)',
                          'fontSize': '150%'})
        ])
    )


def goal_parameters():
    session, engine = db_connect()
    athlete_info = session.query(athlete).filter(athlete.athlete_id == 1).first()
    engine.dispose()
    session.close()
    use_readiness = True if athlete_info.weekly_workout_goal == 99 and athlete_info.weekly_yoga_goal == 99 else False
    use_hrv = True if athlete_info.weekly_workout_goal == 100 and athlete_info.weekly_yoga_goal == 100 else False
    return dbc.Card([
        dbc.CardHeader(html.H4(className='text-left', children='Goals')),
        dbc.CardBody(className='align-items-center text-center', children=[
            generate_db_setting(id='min-workout-time-goal', title='Min. Activity Minutes',
                                value=athlete_info.min_non_warmup_workout_time / 60),
            generate_db_setting(id='weekly-tss-goal', title='Weekly TSS Goal', value=athlete_info.weekly_tss_goal),
            generate_db_setting(id='rr-max-goal', title='High Ramp Rate Injury Threshold',
                                value=athlete_info.rr_max_goal),
            generate_db_setting(id='rr-min-goal', title='Low Ramp Rate Injury Threshold',
                                value=athlete_info.rr_min_goal),
            html.Div(className='row mb-2 mt-2', children=[
                html.H6('Use weekly TSS for fitness goals', className='col-5  mb-0',
                        style={'display': 'inline-block'}),
                daq.BooleanSwitch(
                    id='use-tss-for-goal-switch',
                    on=use_hrv,
                    className='col-2 offset-5'
                )
            ]),
            html.Div(className='row mb-2 mt-2', children=[
                # TODO: Currently results in 7 items on home page... think through consolidating workout/yoga into 1 donut
                html.H6('Use readiness for workout / yoga goals', className='col-5 mb-0',
                        style={'display': 'inline-block'}),
                daq.BooleanSwitch(
                    id='use-readiness-for-goal-switch',
                    on=use_readiness,
                    className='col-2 offset-5'
                )
            ]),
            generate_db_setting(id='weekly-workout-goal', title='Weekly Workout Goal',
                                value=athlete_info.weekly_workout_goal),
            generate_db_setting(id='weekly-yoga-goal', title='Weekly Yoga Goal', value=athlete_info.weekly_yoga_goal),
            generate_db_setting(id='daily-sleep-goal', title='Daily Sleep Goal (hrs)',
                                value=athlete_info.daily_sleep_hr_target),
            generate_db_setting(id='weekly-sleep-score-goal', title='Weekly Sleep Score Goal',
                                value=athlete_info.weekly_sleep_score_goal),
            generate_db_setting(id='weekly-readiness-score-goal', title='Weekly Readiness Score Goal',
                                value=athlete_info.weekly_readiness_score_goal),
            generate_db_setting(id='weekly-activity-score-goal', title='Weekly Activity Score Goal',
                                value=athlete_info.weekly_activity_score_goal)
        ])
    ])


def get_logs():
    logs = ''
    for line in reversed(open("./config/log.log").readlines()):
        logs += line
    return html.Div(
        style={'textAlign': 'left', "whiteSpace": "pre-wrap", "width": '100%', 'overflow': 'auto', 'height': '100%'},
        children=[logs])


def generate_settings_dashboard():
    # Only display reset hrv plan button if there is hrv data (from oura)
    if oura_credentials_supplied:
        reset_hrv_plan_button = html.Div(className='col-12 mb-2', children=[
            dbc.Button('Reset HRV Plan', id='truncate-hrv-button', size='md', color='primary', n_clicks=0)
        ])
    else:
        reset_hrv_plan_button = html.Div(className='col-12 mb-2', children=[
            dbc.Button('Reset HRV Plan', id='truncate-hrv-button', style={'display': 'none'}, n_clicks=0)
        ])

    return html.Div([
        html.Div(id='settings-shelf-1', className='row align-items-start text-center mt-2',
                 children=[
                     html.Div(id='data sources', className='col-lg-3',
                              children=[
                                  dbc.Card(className='mb-2', children=[
                                      dbc.CardHeader(html.H4(className='text-left', children='App Connections')),
                                      dbc.CardBody(children=html.Div(id='api-connections'))
                                  ]),
                              ]),
                     html.Div(id='run-power-zones', className='col-lg-3', children=generate_run_power_zone_card()),
                     html.Div(id='cycle-power-zones', className='col-lg-3', children=generate_cycle_power_zone_card()),
                     html.Div(id='hr-zones', className='col-lg-3', children=generate_hr_zone_card()),
                 ]),

        html.Div(id='settings-shelf-2', className='row align-items-start text-center mt-2', children=[
            html.Div(id='database-container', className='col-lg-4', children=[
                dbc.Card(className='mb-2', children=[
                    dbc.CardHeader(html.H4(className='text-left', children='Database')),
                    dbc.CardBody(children=[
                        html.Div(className='col-12 mb-2', children=[
                            dbc.Button('Refresh', color='primary', size='md',
                                       id='refresh-db-button', n_clicks=0)]),
                        html.Div(className='col-12', children=[
                            dcc.DatePickerSingle(
                                id='truncate-date',
                                with_portal=True,
                                day_size=75,
                                style={'textAlign': 'center'},
                                className='mb-2',
                                month_format='MMM Do, YYYY',
                                placeholder='MMM Do, YYYY',
                                date=datetime.today().date()
                            ),
                            html.Div(className='col-12 mb-2', children=[
                                dbc.Button('Truncate After Date', color='primary', size='md',
                                           id='truncate-date-db-button',
                                           n_clicks=0)]),
                        ]),
                        reset_hrv_plan_button,
                        html.Div(className='col-12 mb-2', children=[
                            dbc.Button('Truncate All', id='truncate-db-button', size='md',
                                       color='primary',
                                       n_clicks=0)]),
                        html.Div(className='col-12 mb-2', children=[dbc.Spinner(color='info', children=[
                            html.Div(id='truncate-refresh-status'),
                            html.Div(id='refresh-status'),
                            html.Div(id='truncate-hrv-status'),
                        ])
                                                                    ]),
                    ])
                ])
            ]),
            html.Div(id='athlete-container', className='col-lg-4',
                     children=[html.Div(id='athlete', children=athlete_card())]),

            html.Div(id='goal-container', className='col-lg-4',
                     children=[html.Div(id='goals', children=goal_parameters())]),
        ]),
        html.Div(id='settings-shelf-3', className='row align-items-start text-center mt-2 mb-2', children=[
            html.Div(id='logs-container', className='col-lg-12',
                     children=[
                         dbc.Card(style={'height': '25vh'}, children=[
                             dbc.CardHeader(className='text-left d-inline-block',
                                            children=[html.H4('Logs', className='d-inline-block mr-2'),
                                                      dbc.Button('Info', id='info-log-button', n_clicks=0,
                                                                 className='mr-2', color='primary', size='sm'),
                                                      dbc.Button('Error', id='error-log-button', n_clicks=0,
                                                                 className='mr-2', color='primary', size='sm'),
                                                      dbc.Button('Debug', id='debug-log-button', n_clicks=0,
                                                                 className='mr-2', color='primary', size='sm', ),
                                                      dbc.Button('Clear Logs', id='clear-log-button',
                                                                 color='primary', size='sm'),
                                                      ]),
                             dbc.CardBody(style={'overflowY': 'scroll'}, children=[
                                 html.Div(id='logs', className='col'),

                                 dcc.Interval(
                                     id='interval-component',
                                     interval=1 * 1000,
                                     # in milliseconds
                                     n_intervals=0
                                 )])
                         ])
                     ])
        ])
    ])


def update_athlete_db_value(value, value_name):
    session, engine = db_connect()
    # TODO: Update athlete_filter if expanding to more users
    athlete_info = session.query(athlete).filter(athlete.athlete_id == 1)
    athlete_info.update({value_name: value})
    # Execute the insert
    try:
        session.commit()
        success = True
        app.server.logger.debug(f'Updated {value_name} to {value}')
    except BaseException as e:
        success = False
        app.server.logger.error(str(e))
    engine.dispose()
    session.close()
    return success


# Callback for updating activity score goal
@app.callback([
    Output('name-input-submit', 'style'),
    Output('name-input-status', 'style'),
    Output('birthday-input-submit', 'style'),
    Output('birthday-input-status', 'style'),
    Output('sex-input-submit', 'style'),
    Output('sex-input-status', 'style'),
    Output('weight-input-submit', 'style'),
    Output('weight-input-status', 'style'),
    Output('rest-hr-input-submit', 'style'),
    Output('rest-hr-input-status', 'style'),
    Output('ride-ftp-input-submit', 'style'),
    Output('ride-ftp-input-status', 'style'),
    Output('run-ftp-input-submit', 'style'),
    Output('run-ftp-input-status', 'style'),
    Output('weekly-activity-score-goal-input-submit', 'style'),
    Output('weekly-activity-score-goal-input-status', 'style'),
    Output('daily-sleep-goal-input-submit', 'style'),
    Output('daily-sleep-goal-input-status', 'style'),
    Output('weekly-tss-goal-input-submit', 'style'),
    Output('weekly-tss-goal-input-status', 'style'),
    Output('rr-max-goal-input-submit', 'style'),
    Output('rr-max-goal-input-status', 'style'),
    Output('rr-min-goal-input-submit', 'style'),
    Output('rr-min-goal-input-status', 'style'),
    Output('min-workout-time-goal-input-submit', 'style'),
    Output('min-workout-time-goal-input-status', 'style'),
    Output('weekly-workout-goal-input-submit', 'style'),
    Output('weekly-workout-goal-input-status', 'style'),
    Output('weekly-yoga-goal-input-submit', 'style'),
    Output('weekly-yoga-goal-input-status', 'style'),
    Output('weekly-sleep-score-goal-input-submit', 'style'),
    Output('weekly-sleep-score-goal-input-status', 'style'),
    Output('weekly-readiness-score-goal-input-submit', 'style'),
    Output('weekly-readiness-score-goal-input-status', 'style'),
    Output('cycle-zone1-input-submit', 'style'),
    Output('cycle-zone1-input-status', 'style'),
    Output('cycle-zone2-input-submit', 'style'),
    Output('cycle-zone2-input-status', 'style'),
    Output('cycle-zone3-input-submit', 'style'),
    Output('cycle-zone3-input-status', 'style'),
    Output('cycle-zone4-input-submit', 'style'),
    Output('cycle-zone4-input-status', 'style'),
    Output('cycle-zone5-input-submit', 'style'),
    Output('cycle-zone5-input-status', 'style'),
    Output('cycle-zone6-input-submit', 'style'),
    Output('cycle-zone6-input-status', 'style'),
    Output('run-zone1-input-submit', 'style'),
    Output('run-zone1-input-status', 'style'),
    Output('run-zone2-input-submit', 'style'),
    Output('run-zone2-input-status', 'style'),
    Output('run-zone3-input-submit', 'style'),
    Output('run-zone3-input-status', 'style'),
    Output('run-zone4-input-submit', 'style'),
    Output('run-zone4-input-status', 'style'),
    Output('hr-zone1-input-submit', 'style'),
    Output('hr-zone1-input-status', 'style'),
    Output('hr-zone2-input-submit', 'style'),
    Output('hr-zone2-input-status', 'style'),
    Output('hr-zone3-input-submit', 'style'),
    Output('hr-zone3-input-status', 'style'),
    Output('hr-zone4-input-submit', 'style'),
    Output('hr-zone4-input-status', 'style'),
],
    [
        Input('name-input-submit', 'n_clicks'),
        Input('birthday-input-submit', 'n_clicks'),
        Input('sex-input-submit', 'n_clicks'),
        Input('weight-input-submit', 'n_clicks'),
        Input('rest-hr-input-submit', 'n_clicks'),
        Input('ride-ftp-input-submit', 'n_clicks'),
        Input('run-ftp-input-submit', 'n_clicks'),
        Input('weekly-activity-score-goal-input-submit', 'n_clicks'),
        Input('daily-sleep-goal-input-submit', 'n_clicks'),
        Input('weekly-tss-goal-input-submit', 'n_clicks'),
        Input('rr-max-goal-input-submit', 'n_clicks'),
        Input('rr-min-goal-input-submit', 'n_clicks'),
        Input('min-workout-time-goal-input-submit', 'n_clicks'),
        Input('weekly-workout-goal-input-submit', 'n_clicks'),
        Input('weekly-yoga-goal-input-submit', 'n_clicks'),
        Input('weekly-sleep-score-goal-input-submit', 'n_clicks'),
        Input('weekly-readiness-score-goal-input-submit', 'n_clicks'),
        Input('cycle-zone1-input-submit', 'n_clicks'),
        Input('cycle-zone2-input-submit', 'n_clicks'),
        Input('cycle-zone3-input-submit', 'n_clicks'),
        Input('cycle-zone4-input-submit', 'n_clicks'),
        Input('cycle-zone5-input-submit', 'n_clicks'),
        Input('cycle-zone6-input-submit', 'n_clicks'),
        Input('run-zone1-input-submit', 'n_clicks'),
        Input('run-zone2-input-submit', 'n_clicks'),
        Input('run-zone3-input-submit', 'n_clicks'),
        Input('run-zone4-input-submit', 'n_clicks'),
        Input('hr-zone1-input-submit', 'n_clicks'),
        Input('hr-zone2-input-submit', 'n_clicks'),
        Input('hr-zone3-input-submit', 'n_clicks'),
        Input('hr-zone4-input-submit', 'n_clicks'),

    ],
    [
        State('name-input', 'value'),
        State('birthday-input', 'value'),
        State('sex-input', 'value'),
        State('weight-input', 'value'),
        State('rest-hr-input', 'value'),
        State('ride-ftp-input', 'value'),
        State('run-ftp-input', 'value'),
        State('weekly-activity-score-goal-input', 'value'),
        State('daily-sleep-goal-input', 'value'),
        State('weekly-tss-goal-input', 'value'),
        State('rr-max-goal-input', 'value'),
        State('rr-min-goal-input', 'value'),
        State('min-workout-time-goal-input', 'value'),
        State('weekly-workout-goal-input', 'value'),
        State('weekly-yoga-goal-input', 'value'),
        State('weekly-sleep-score-goal-input', 'value'),
        State('weekly-readiness-score-goal-input', 'value'),
        State('cycle-zone1-input', 'value'),
        State('cycle-zone2-input', 'value'),
        State('cycle-zone3-input', 'value'),
        State('cycle-zone4-input', 'value'),
        State('cycle-zone5-input', 'value'),
        State('cycle-zone6-input', 'value'),
        State('run-zone1-input', 'value'),
        State('run-zone2-input', 'value'),
        State('run-zone3-input', 'value'),
        State('run-zone4-input', 'value'),
        State('hr-zone1-input', 'value'),
        State('hr-zone2-input', 'value'),
        State('hr-zone3-input', 'value'),
        State('hr-zone4-input', 'value'),
    ])
def save_athlete_settings(
        name_click, birthday_click, sex_click, weight_click, rest_hr_click, ride_ftp_click, run_ftp_click, wk_act_click,
        slp_goal_click, tss_goal_click, rrmax_click, rrmin_click, min_workout_click, workout_click, yoga_click,
        slp_click, rd_click, cycle_zone1_click, cycle_zone2_click, cycle_zone3_click, cycle_zone4_click,
        cycle_zone5_click, cycle_zone6_click, run_zone1_click, run_zone2_click, run_zone3_click, run_zone4_click,
        hr_zone1_click, hr_zone2_click, hr_zone3_click, hr_zone4_click, name_value, birthday_value, sex_value,
        weight_value, rest_hr_value, ride_ftp_value, run_ftp_value, wk_act_value, slp_goal_value, tss_goal_value,
        rrmax_value, rrmin_value, min_workout_value, workout_value, yoga_value, slp_value, rd_value,
        cycle_zone1_value, cycle_zone2_value, cycle_zone3_value, cycle_zone4_value, cycle_zone5_value,
        cycle_zone6_value, run_zone1_value, run_zone2_value, run_zone3_value, run_zone4_value, hr_zone1_value,
        hr_zone2_value, hr_zone3_value, hr_zone4_value,

):
    num_metrics = 31
    output_styles = []
    for _ in range(num_metrics):
        output_styles.extend([{'display': 'inline-block', 'border': '0px'}, {
            'display': 'none'}])

    ctx = dash.callback_context
    if ctx.triggered:
        latest = ctx.triggered[0]['prop_id'].split('.')[0]
        latest_dict = {'name-input-submit': 'name',
                       'birthday-input-submit': 'birthday',
                       'sex-input-submit': 'sex',
                       'weight-input-submit': 'weight',
                       'rest-hr-input-submit': 'rest_hr',
                       'ride-ftp-input-submit': 'ride_ftp',
                       'run-ftp-input-submit': 'run_ftp',
                       'weekly-activity-score-goal-input-submit': 'weekly_activity_score_goal',
                       'daily-sleep-goal-input-submit': 'daily_sleep_hr_target',
                       'weekly-tss-goal-input-submit': 'weekly_tss_goal',
                       'rr-max-goal-input-submit': 'rr_max_goal',
                       'rr-min-goal-input-submit': 'rr_min_goal',
                       'min-workout-time-goal-input-submit': 'min_non_warmup_workout_time',
                       'weekly-workout-goal-input-submit': 'weekly_workout_goal',
                       'weekly-yoga-goal-input-submit': 'weekly_yoga_goal',
                       'weekly-sleep-score-goal-input-submit': 'weekly_sleep_score_goal',
                       'weekly-readiness-score-goal-input-submit': 'weekly_readiness_score_goal',
                       'cycle-zone1-input-submit': 'cycle_power_zone_threshold_1',
                       'cycle-zone2-input-submit': 'cycle_power_zone_threshold_2',
                       'cycle-zone3-input-submit': 'cycle_power_zone_threshold_3',
                       'cycle-zone4-input-submit': 'cycle_power_zone_threshold_4',
                       'cycle-zone5-input-submit': 'cycle_power_zone_threshold_5',
                       'cycle-zone6-input-submit': 'cycle_power_zone_threshold_6',
                       'run-zone1-input-submit': 'run_power_zone_threshold_1',
                       'run-zone2-input-submit': 'run_power_zone_threshold_2',
                       'run-zone3-input-submit': 'run_power_zone_threshold_3',
                       'run-zone4-input-submit': 'run_power_zone_threshold_4',
                       'hr-zone1-input-submit': 'hr_power_zone_threshold_1',
                       'hr-zone2-input-submit': 'hr_power_zone_threshold_2',
                       'hr-zone3-input-submit': 'hr_power_zone_threshold_3',
                       'hr-zone4-input-submit': 'hr_power_zone_threshold_4',
                       }

        output_indexer = [
            'name',
            'birthday',
            'sex',
            'weight',
            'rest_hr',
            'ride_ftp',
            'run_ftp',
            'weekly_activity_score_goal',
            'daily_sleep_hr_target',
            'weekly_tss_goal',
            'rr_max_goal',
            'rr_min_goal',
            'min_non_warmup_workout_time',
            'weekly_workout_goal',
            'weekly_yoga_goal',
            'weekly_sleep_score_goal',
            'weekly_readiness_score_goal',
            'cycle_power_zone_threshold_1',
            'cycle_power_zone_threshold_2',
            'cycle_power_zone_threshold_3',
            'cycle_power_zone_threshold_4',
            'cycle_power_zone_threshold_5',
            'cycle_power_zone_threshold_6',
            'run_power_zone_threshold_1',
            'run_power_zone_threshold_2',
            'run_power_zone_threshold_3',
            'run_power_zone_threshold_4',
            'hr_power_zone_threshold_1',
            'hr_power_zone_threshold_2',
            'hr_power_zone_threshold_3',
            'hr_power_zone_threshold_4',

        ]
        values = {
            'name': name_value,
            'birthday': birthday_value,
            'sex': sex_value,
            'weight': weight_value,
            'rest_hr': rest_hr_value,
            'ride_ftp': ride_ftp_value,
            'run_ftp': run_ftp_value,
            'weekly_activity_score_goal': wk_act_value,
            'daily_sleep_hr_target': slp_goal_value,
            'weekly_tss_goal': tss_goal_value,
            'rr_max_goal': rrmax_value,
            'rr_min_goal': rrmin_value,
            'min_non_warmup_workout_time': min_workout_value,
            'weekly_workout_goal': workout_value,
            'weekly_yoga_goal': yoga_value,
            'weekly_sleep_score_goal': slp_value,
            'weekly_readiness_score_goal': rd_value,
            'cycle_power_zone_threshold_1': cycle_zone1_value,
            'cycle_power_zone_threshold_2': cycle_zone2_value,
            'cycle_power_zone_threshold_3': cycle_zone3_value,
            'cycle_power_zone_threshold_4': cycle_zone4_value,
            'cycle_power_zone_threshold_5': cycle_zone5_value,
            'cycle_power_zone_threshold_6': cycle_zone6_value,
            'run_power_zone_threshold_1': run_zone1_value,
            'run_power_zone_threshold_2': run_zone2_value,
            'run_power_zone_threshold_3': run_zone3_value,
            'run_power_zone_threshold_4': run_zone4_value,
            'hr_power_zone_threshold_1': hr_zone1_value,
            'hr_power_zone_threshold_2': hr_zone2_value,
            'hr_power_zone_threshold_3': hr_zone3_value,
            'hr_power_zone_threshold_4': hr_zone4_value,
        }

        index1 = output_indexer.index(latest_dict[latest]) * 2
        index2 = index1 + 1
        # Update value in db
        success = update_athlete_db_value(values[latest_dict[latest]], latest_dict[latest])

        if success:
            output_styles[index1] = {'display': 'none'}
            output_styles[index2] = {'color': 'green', 'fontSize': '150%'}
        else:
            output_styles[index1] = {'display': 'inline-block', 'border': '0px'}
            output_styles[index2] = {'display': 'none'}

    return output_styles


# Callback to prevent both readiness/hrv goal settings to be enabled at the same time
@app.callback(
    Output('use-tss-for-goal-switch', 'disabled'),
    [Input('use-readiness-for-goal-switch', 'on')],
    [State('use-tss-for-goal-switch', 'on')]
)
def disable_hrv(readiness, hrv):
    if not readiness and not hrv:
        return False
    else:
        return readiness


@app.callback(
    Output('use-readiness-for-goal-switch', 'disabled'),
    [Input('use-tss-for-goal-switch', 'on')],
    [State('use-tss-for-goal-switch', 'on')]
)
def disable_readiness(hrv, readiness):
    if not readiness and not hrv:
        return False
    else:
        return hrv


# Callback for showing/hiding workout/yoga goal settings
@app.callback([
    Output('weekly-workout-goal', 'style'),
    Output('weekly-yoga-goal', 'style')],
    [Input('use-readiness-for-goal-switch', 'on'), Input('use-tss-for-goal-switch', 'on')],
    [State('use-readiness-for-goal-switch', 'on'), State('use-tss-for-goal-switch', 'on')]
)
def set_fitness_goals(readiness_dummy, hrv_dummy, readiness_switch, hrv_switch):
    session, engine = db_connect()
    athlete_info = session.query(athlete).filter(athlete.athlete_id == 1).first()

    if readiness_switch:
        style = {'display': 'none'}
        weekly_workout_goal, weekly_yoga_goal = 99, 99
    elif hrv_switch:
        style = {'display': 'none'}
        weekly_workout_goal, weekly_yoga_goal = 100, 100
    else:
        style = {}
        weekly_workout_goal, weekly_yoga_goal = 3, 3

    try:
        if athlete_info.weekly_yoga_goal != weekly_yoga_goal and athlete_info.weekly_workout_goal != weekly_workout_goal:
            app.server.logger.info('Updating weekly yoga goal to {}'.format(
                weekly_yoga_goal if weekly_yoga_goal != 99 or weekly_yoga_goal != 100 else 'readiness score based'))
            app.server.logger.info('Updating weekly workout goal to {}'.format(
                weekly_workout_goal if weekly_workout_goal != 99 or weekly_workout_goal != 100 else 'readiness score based'))
            athlete_info.weekly_yoga_goal = weekly_yoga_goal
            athlete_info.weekly_workout_goal = weekly_workout_goal
            session.commit()
    except BaseException as e:
        app.server.logger.error(e)
    engine.dispose()
    session.close()

    return style, style


@app.callback(Output('api-connections', 'children'),
              [Input('submit-settings-button', 'n_clicks')])
def update_api_connection_status(n_clicks):
    if n_clicks and n_clicks > 0:
        return html.Div(children=[
            html.Div(className='row ', children=[check_oura_connection()]),
            html.Div(className='row', children=[check_strava_connection()]),
            html.Div(className='row', children=[check_withings_connection()])
        ])


# Manual Refresh
@app.callback(Output('refresh-status', 'children'),
              [Input('refresh-db-button', 'n_clicks')])
def refresh(n_clicks):
    if n_clicks > 0:
        app.server.logger.info('Manually refreshing database tables...')
        refresh_database(refresh_method='manual')
        return html.H6('Refresh Complete')
    return ''


# Truncate hrv_workout_step_log (reset HRV Plan)
@app.callback(Output('truncate-hrv-status', 'children'),
              [Input('truncate-hrv-button', 'n_clicks')],
              [State('truncate-date', 'date')])
def reset_hrv_plan(n_clicks, hrv_date):
    if n_clicks > 0:
        app.server.logger.info('Resetting HRV workout plan workflow to step 0 on {}'.format(hrv_date))
        try:
            session, engine = db_connect()
            session.execute(delete(hrvWorkoutStepLog).where(hrvWorkoutStepLog.date > hrv_date))
            query = session.query(hrvWorkoutStepLog).filter(hrvWorkoutStepLog.date == hrv_date).first()
            query.hrv_workout_step = 0
            query.hrv_workout_step_desc = 'Low'
            query.rationale = 'You manually restarted the hrv workout plan workflow today'
            query.athlete_id = 1
            query.completed = 0
            session.commit()
            min_non_warmup_workout_time = session.query(athlete).filter(
                athlete.athlete_id == 1).first().min_non_warmup_workout_time
            hrv_training_workflow(min_non_warmup_workout_time)
            return html.H6('HRV Plan Reset!')
        except BaseException as e:
            session.rollback()
            app.server.logger.error('Error resetting hrv workout plan: {}'.format(e))
            return html.H6('Error Resetting HRV Plan')
        engine.dispose()
        session.close()
    return ''


# Truncate database
@app.callback(Output('truncate-refresh-status', 'children'),
              [Input('truncate-db-button', 'n_clicks'),
               Input('truncate-date-db-button', 'n_clicks')],
              [State('truncate-date', 'date')])
def truncate_and_refresh(n_clicks, n_clicks_date, truncateDate):
    if n_clicks > 0:
        app.server.logger.info('Manually truncating and refreshing database tables...')
        try:
            refresh_database(refresh_method='manual', truncate=True)
            return html.H6('Truncate and Load Complete')
        except BaseException as e:
            return html.H6('Error with Truncate and Load')
    elif n_clicks_date > 0:
        app.server.logger.info(
            'Manually truncating and refreshing database tables after {}...'.format(truncateDate))
        try:
            refresh_database(refresh_method='manual', truncateDate=truncateDate)
            return html.H6('Truncate and Load Complete')
        except:
            return html.H6('Error with Truncate and Load')
    return ''


# Refresh Logs Interval
@app.callback(Output('logs', 'children'),
              [Input('interval-component', 'n_intervals')])
def clear_logs(n):
    return get_logs()


# Clear Logs button
@app.callback(Output('clear-log-dummy', 'children'),
              [Input('clear-log-button', 'n_clicks')])
def clear_logs(n_clicks):
    if n_clicks and n_clicks > 0:
        open('./config/log.log', 'w').close()
        app.server.logger.debug('Logs manually cleared')
    return 'Logs last cleared at {}'.format(datetime.utcnow())


# Set log level
@app.callback([Output('info-log-button', 'style'),
               Output('error-log-button', 'style'),
               Output('debug-log-button', 'style')],
              [Input('info-log-button', 'n_clicks'),
               Input('error-log-button', 'n_clicks'),
               Input('debug-log-button', 'n_clicks')]
              )
def set_log_level(info_n_clicks, error_n_clicks, debug_n_clicks):
    styles = {'INFO': {'marginRight': '1%'}, 'ERROR': {'marginRight': '1%'}, 'DEBUG': {'marginRight': '1%'}}
    latest_dict = {'info-log-button': 'INFO', 'error-log-button': 'ERROR', 'debug-log-button': 'DEBUG'}
    ctx = dash.callback_context

    if ctx.triggered:
        latest = latest_dict[ctx.triggered[0]['prop_id'].split('.')[0]]
        config.set('logger', 'level', latest)
        with open('./config/config.ini', 'w') as configfile:
            config.write(configfile)
            # Set to info to show message in log, then switch to selected level
            app.server.logger.setLevel('INFO')
            app.server.logger.info('Log level set to {}'.format(latest))
            app.server.logger.setLevel(latest)

    current_log_level = config.get('logger', 'level')
    styles[current_log_level] = {'marginRight': '1%', 'color': '#64D9EC', 'borderColor': '#64D9EC'}
    return styles['INFO'], styles['ERROR'], styles['DEBUG']


# Auth Callback #
# Callback for authorizing withings tokens
@app.callback(Output('token-dummy', 'children'),
              [Input('submit-settings-button', 'n_clicks')],
              [State(server.config["LOCATION_COMPONENT_ID"], 'search')]
              )
def update_tokens(n_clicks, search):
    if 'oura' in search:
        if not oura_connected():
            search = search.replace('?oura', '')
            auth_code = re.findall('=(?<=code\=)(.*?)(?=\&)', search)[0]
            oura_auth_client.fetch_access_token(auth_code)
            save_oura_token(oura_auth_client.session.token)

    if 'strava' in search:
        if not strava_connected():
            search = search.replace('?strava', '')
            auth_code = re.findall('=(?<=code\=)(.*?)(?=\&)', search)[0]
            token_response = strava_auth_client.exchange_code_for_token(client_id=config.get('strava', 'client_id'),
                                                                        client_secret=config.get('strava',
                                                                                                 'client_secret'),
                                                                        code=auth_code)
        save_strava_token(token_response)

    if 'withings' in search:
        if not withings_connected():
            search = search.replace('?withings', '')
            auth_code = re.findall('=(?<=code\=)(.*?)(?=\&)', search)[0]
            creds = withings_auth_client.get_credentials(auth_code)
            save_withings_token(creds)

    return None


# Peloton dropdown options
@app.callback(
    [Output('peloton-bookmark-class-type-dropdown', 'value'),
     Output('peloton-bookmark-class-type-dropdown', 'options')],
    [Input('peloton-bookmark-fitness-discipline-dropdown', 'value'),
     Input('peloton-bookmark-effort-dropdown', 'value')]
)
def query_peloton_bookmark_settings(fitness_discipline, effort):
    if fitness_discipline and effort:
        # Query athlete table for current peloton settings to show in value of dropdown
        session, engine = db_connect()
        athlete_bookmarks = json.loads(session.query(athlete.peloton_auto_bookmark_ids).filter(
            athlete.athlete_id == 1).first().peloton_auto_bookmark_ids)
        engine.dispose()
        session.close()
        if athlete_bookmarks:
            try:
                athlete_bookmarks = ast.literal_eval(athlete_bookmarks.get(fitness_discipline).get(effort))
                values = [x["value"] for x in athlete_bookmarks]
            except:
                values = []
        else:
            values = []
        # Query all possible options from peloton api for dropdown options
        class_types = get_class_types()[fitness_discipline]

        return values, [{'label': f'{v}', 'value': f'{k}'} for k, v in class_types.items()]
    else:
        return [], []


# Peloton save to athlete table
@app.callback(
    Output('peloton-bookmark-input-status', 'style'),
    [Input('peloton-bookmark-input-submit', 'n_clicks'),
     Input('peloton-bookmark-fitness-discipline-dropdown', 'value'),
     Input('peloton-bookmark-effort-dropdown', 'value')],
    [State('peloton-bookmark-class-type-dropdown', 'options'),
     State('peloton-bookmark-class-type-dropdown', 'value')]
)
def save_peloton_bookmark_settings(n_clicks, fitness_discipline, effort, options, values):
    latest = None
    ctx = dash.callback_context
    if ctx.triggered:
        latest = ctx.triggered[0]['prop_id'].split('.')[0]

    if latest:
        if latest == 'peloton-bookmark-fitness-discipline-dropdown' or latest == 'peloton-bookmark-effort-dropdown':
            return {'display': 'none'}

        elif fitness_discipline and effort and latest == 'peloton-bookmark-input-submit':
            # Query athlete table to get current bookmark settings
            session, engine = db_connect()
            athlete_bookmarks = session.query(athlete.peloton_auto_bookmark_ids).filter(
                athlete.athlete_id == 1).first()

            # update peloton bookmark settings per the inputs
            athlete_bookmarks_json = json.loads(athlete_bookmarks.peloton_auto_bookmark_ids)

            # Check if fitness discipline exists
            if not athlete_bookmarks_json.get(fitness_discipline):
                athlete_bookmarks_json[fitness_discipline] = {}
            # Check if fitness discipline / effort exists
            if not athlete_bookmarks_json.get(fitness_discipline).get(effort):
                athlete_bookmarks_json[fitness_discipline][effort] = {}

            athlete_bookmarks_json[fitness_discipline][effort] = json.dumps(
                [x for x in options if x['value'] in values])

            session.query(athlete.peloton_auto_bookmark_ids).filter(
                athlete.athlete_id == 1).update({athlete.peloton_auto_bookmark_ids: json.dumps(athlete_bookmarks_json)})

            # write back to database
            session.commit()

            engine.dispose()
            session.close()
            return {'color': 'green', 'fontSize': '150%'}
        else:
            return {'display': 'none'}
    else:
        return {'display': 'none'}


# Main Dashboard Generation Callback with password modal
@app.callback(
    [Output('settings-layout', 'children'),
     Output('settings-modal', 'is_open')],
    [Input('submit-settings-button', 'n_clicks')],
    [State('settings-password', 'value')]
)
def settings_dashboard(n_clicks, password):
    if n_clicks and n_clicks > 0:
        if password == config.get('settings', 'password'):
            return generate_settings_dashboard(), False
    else:
        return [], True
