from __future__ import division
import os
import eventlet
eventlet.monkey_patch()

import time
import csv

from collections import defaultdict
from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit, disconnect
from flask_cas import CAS, login, logout, login_required

app = Flask(__name__)

socketio = SocketIO(app)
cas = CAS(app)

app.debug = True
app.config['SECRET_KEY'] = 'secret!'
app.config['CAS_SERVER'] = 'https://login.umd.edu'
app.config['CAS_LOGIN_ROUTE'] = '/cas/login'
app.config['CAS_AFTER_LOGIN'] = 'index'

BID_THRESHOLD = 0.75

ADMINS = set()
ADMINS.add('cgonza1')
ADMINS.add('tantony')
ADMINS.add('jlewis10')

has_voted = set()
not_voted = set()
clients = set()
clients_count = defaultdict(int)

votes = defaultdict(lambda: defaultdict(int)) # 2D defaultdict, where votes[choice][rush_name] = count
current_name = ""
current_abstain = ""
is_voting = False

#
# Initialization
#

def make_id_map():
    temp = defaultdict(str)
    SITE_ROOT = os.path.realpath(os.path.dirname(__file__))
    map_path = os.path.join(SITE_ROOT, 'static', 'ids.csv')
    with open(map_path) as csvfile:
        reader = csv.reader(open(map_path, "rb"))
        for row in reader:
            temp[row[0]] = row[1]
    return temp

id_map = make_id_map()

#
# Utility functions
#

def generate_vote_report():
    report_fmt = ("Vote Report: {}"
        "\nYes: {:.2f}%"
        "\nNo: {:.2f}%"
        "\nAbstain: {:.2f}%"
        "\nBid? {}")
    yes = votes['yes'][current_name]
    no = votes['no'][current_name]
    abstain = votes['abstain'][current_name]
    total  = yes + no + abstain
    bid = ""
    if (yes/total) >= BID_THRESHOLD:
        bid = "YES"
    else:
        bid = "NO"
    report = report_fmt.format(current_name, yes * 100/total, no * 100/total, abstain * 100/total, bid)
    return report


#
# Route definition
#

@app.route('/')
@login_required
def index():
    # Check if already connected, only ADMINS are allowed to do this
    if cas.username not in id_map:
        return render_template('error.html', error="denied")

    if cas.username not in ADMINS and cas.username in clients:
        return render_template('error.html', error="duplicate")
    else:
        return render_template('index.html', username = cas.username)

@app.route('/admin')
@login_required
def admin_panel():
    if cas.username not in ADMINS:
        return render_template('error.html', error="denied")
    else:
        return render_template('admin.html')

#
# Admin socket context functions
#

@socketio.on('connect', namespace='/admin')
def admin_connect():
    print("Admin connected: " + cas.username)

@socketio.on('disconnect', namespace='/admin')
def admin_disconnect():
    print("Admin disconnected: " + cas.username)

@socketio.on('start_vote', namespace='/admin')
def start_vote(msg):
    if cas.username in ADMINS:
        has_voted.clear()
        global is_voting
        global current_name
        global current_abstain
        global votes

        is_voting = True
        current_name = msg['name']
        current_abstain = msg['abstain']
        print("name is " + current_name)
        print("abstain is " + current_abstain)
        print("is_voting is " + str(is_voting))
        for key in votes:
            votes[key][current_name] = 0
        emit('vote_start', {'name': current_name, 'abstain': current_abstain}, namespace='/vote', broadcast=True)

@socketio.on('end_vote', namespace='/admin')
def end_vote():
    if cas.username in ADMINS:
        if is_voting:
            print("ending vote...")
            global is_voting
            is_voting = False
            report = generate_vote_report()
            print("Report is: " + report)
            emit('vote_report', {'report': report}, namespace='/admin', broadcast=True)
            emit('vote_end', namespace='/vote', broadcast=True)

@socketio.on('get_not_voted', namespace='/admin')
def query_not_voted():


#
# Socket context functions
#

@socketio.on('submit_vote', namespace='/vote')
def function(vote):
    global votes
    global has_voted
    global not_voted
    has_voted.add(cas.username)
    print("not voted=" + str(not_voted))
    not_voted = clients - has_voted
    votes[vote['bid']][current_name] += 1
    votes_cast = 0
    votes_left = 0

    for key in votes:
        votes_cast += votes[key][current_name]

    votes_left = len(clients) - votes_cast
    print("votes is ", votes)
    print("current_name = " + current_name)
    print("current_abstain = " + current_abstain)
    emit('vote_submitted', {'name':id_map[cas.username], 'votes_cast': votes_cast, 'votes_left': votes_left}, namespace='/admin', broadcast=True)

@socketio.on('connect', namespace='/vote')
def socket_attach():
    clients.add(cas.username)
    clients_count[cas.username] += 1
    print('Clients is: ' + str(clients))
    print('Client count: ' + str(clients_count))
    print('Socket attached: ' + cas.username)
    print('is_voting = ' + str(is_voting))
    if is_voting:
        print("Emitting vote_start to client connected after voting has started")
        emit('vote_start', {'name': current_name, 'abstain': current_abstain})

@socketio.on('disconnect', namespace='/vote')
def socket_detach():
    print('Socket disconnected from user: ' + cas.username)
    clients_count[cas.username] -= 1
    print('Client count: ' + str(clients_count))
    if cas.username in clients and clients_count[cas.username] == 0:
        print('Removing: ' + cas.username)
        clients.remove(cas.username)
    print('Clients is: ' + str(clients))

if __name__ == "__main__":
    # Fetch the environment variable (so it works on Heroku):
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
