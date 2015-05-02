"""
Name:       Maturing Progress Graph
Created:    2015-04-28
Version:    0.1
Published:  <not jet>
Author:     Kai Husmann<kai.husmann+anki@gmail.com>
Desc:       Generates a new graph that shows the maturing progress, i.e. cards maturing over time.
Thanks:     This project was based on the work of
            Kenishi (Maturing Cards AddOn)
            Thomas Tempé (Progress Graph AddOn)
            Damien Elmes (Anki)
Contribute: https://github.com/k-husmann/ankiplug.git
Licence:    GNU GENERAL PUBLIC LICENSE Version 2, June 1991
"""

##### SETTINGS ##################################

# colours
from anki.stats import colLearn, colMature, colYoung, colUnseen
colMatureBar                        = "#72A5D9"      # weaker blue
colForgetBar                        = "#DE8073"      # weaker red
colMatureLine                       = colMature
colKnownLine                        = "#000"

# always full history
alwaysShowFullHistory               = True
# whether, after creating the progress graph, the revlog-based result should be
# compared to the cards table, thereby checking for revlog-errors.
performRevlogInconsistencyCheck     = True


##### LIBANKI ###################################

import anki
import anki.stats
from anki.hooks import wrap, addHook
from aqt.utils import showInfo
from aqt import mw
from aqt.qt import QAction, SIGNAL

def registerMenuEntry(title=None, menu='Tools'):
    """Decorator to create a menu entry for a function"""
    menu = getattr(mw.form, 'menu' + menu)
    def _regMenu(function, title=title, menu=menu):
        if not title: title = function.__name__
        action = QAction(title, mw)
        mw.connect(action, SIGNAL("triggered()"), function)
        menu.addAction(action)
    return _regMenu


##### DEBUGGING #################################

try:
    import os
    DEBUG = os.environ.get("KHSDEBUG")
except:
    DEBUG = False

def dprint(arg):
    if DEBUG:
        print "MaturingProgress:", arg
dprint("Logging initialized")


##### ENTRY POINTS ##############################

def progressGraph(self, **kwargs):
    """Parses revlog entries to check when cards matured.

    For each revlog it checks if a card passed the mature-boundary (ivl=21) or the 'known'-boundary (ivl=365) in any direction.
    Out of this data a graph is generated.
    If performRevlogInconsistencyCheck is True it finally checks if the count of cards with an ivl above said intervals matches the accumulated data from revlog.
    If not a warning is put under the graph, indicating that repairRevlogLastIvl should be run.
    """

    old = kwargs['_old'] # Reference back to the wrapped graph

    if alwaysShowFullHistory:
        # always graph over total deck time
        # XXX for now this fixes the need of raising initial cumulative value if days != None.
        days = None; chunk = 30; timetickLabel=_("mo") # None/7/w, None/1/d
    else:
        timetickLabel=None # i.e. let cards.py choose it
        if self.type == 0:
            days = 30; chunk = 1
        elif self.type == 1:
            days = 52; chunk = 7
        else:
            days = None; chunk = 30

    return plotProgressGraph(self, chunk, days, timetickLabel, "Maturing Progress") + old(self)

@registerMenuEntry(title="MaturingProgress: revlog-repair")
def repairRevlogLastIvl():
    """Checks revlog entries for inconsistencies.
    
    If lastivl doesn't match ivl of last revlog entry it adjusts lastivl
    accordingly. Finally it also checks if the last revlog entries ivl matches
    that of the card and adjusts it if necessary
    """

    sql='''\
        SELECT DISTINCT cards.id
        FROM cards JOIN revlog ON cards.id = revlog.cid
    ''' # ids of all cards which have revlogs
    r = mw.col.db.list(sql) # all: array of rowtuples, scalar: one value, list: list of one-values, first: one row

    bad_livl    = []
    bad_ivl     = []

    for cid in r:
        #if cid == 1312481332306: showInfo("we'rehere")
        collectBadRevlogs(cid, bad_livl, bad_ivl)

    sql='''\
        UPDATE revlog
        SET lastIvl=?
        WHERE id=?
    '''
    mw.col.db.executemany(sql, bad_livl)

    sql='''\
        UPDATE revlog
        SET ivl=?
        WHERE id=?
    '''
    mw.col.db.executemany(sql, bad_ivl)

    showInfo("LastIvl updates: %d; Ivl updates: %d" % (len(bad_livl), len(bad_ivl)))


##### REGISTER WITH ANKI ########################

if DEBUG:
    anki.stats.CollectionStats.todayStats = wrap(anki.stats.CollectionStats.todayStats, progressGraph, pos="around")
else:
    anki.stats.CollectionStats.repsGraph = wrap(anki.stats.CollectionStats.repsGraph, progressGraph, pos="around")


##### METHODS ###################################

def plotProgressGraph(self, chunk, days, timetickLabel, title):
    sqldata = getProgressData(self, days, chunk)
    if not sqldata: return ""

    mature, known = accumdata(sqldata)
    data = [
        dict(data=mature['good'],   color=colMatureBar, yaxis=1, stack=1, label="matured"),
        dict(data=mature['fail'],   color=colForgetBar, yaxis=1, stack=2, label="failed"),

        dict(data=mature['accum'],  color=colMatureLine, yaxis=2, stack=3, bars={'show': False}, lines={'show':True }, label="matured (cum.)"),
        dict(data=known['accum'],   color=colKnownLine,  yaxis=2, stack=4, bars={'show': False}, lines={'show':True }, label="known (cum.)"),
    ]

    yaxes = [
              dict(position="left"),
              dict(position="right")
            ]

    txt = self._title("Maturing Progress",
                      "Maturing of the deck over time.")

    autotimeticks = (timetickLabel == None)
    txt += self._graph(
            id="khs_maturingprogress",
            ylabel="maturing cards",
            ylabel2="deck progress",
            data=data,
            conf=dict(
                xaxis=dict(max=0.5),
                yaxes=yaxes,
                timeTicks=timetickLabel
            ),
            timeTicks=autotimeticks
    )
    txt += "Mature: " + str(mature['total'][0]) + ' - ' +  str(mature['total'][1]) + " = " + str(mature['accum'][-1][1]) + '<br>'
    txt += "Known: "  + str(known['total'][0])  + ' - ' +  str(known['total'][1])  + " = " + str( known['accum'][-1][1]) + '<br>'
    txt += "<small>Cards with an interval of over a year are considered <i>known</i> cards (it's a subset of matured cards).</small><br>"

    txt += '<small>'
    if performRevlogInconsistencyCheck:
        m, k = getProgressCheckData(self)
        if (m != mature['accum'][-1][1]) or (k != known['accum'][-1][1]):
            txt += '<font color="red">Revlog inconsistencies found: Please run the revlog-repair feature (@see tools menu).</font><br>'
        elif DEBUG:
            txt +='Revlog inconsistency check passed.'
    else:
        txt +="If the graph looks weird it's probably due to revlog inconsistencies: try the revlog-repair feature (@see tools menu)."
    txt +='</small>'


    return txt

def getProgressData(self, num=7, chunk=1):
    # num= days to go back, None=beginning; chunk=number of days contained by one chunk
    lims = []
    if num is not None:
        lims.append("revlog.id > %d" % (
            (self.col.sched.dayCutoff-(num*chunk*86400))*1000))
    lim = self._revlogLimit()
    if lim:
        lims.append(lim)
    if lims:
        lim = "where " + " and ".join(lims)
    else:
        lim = ""

    if alwaysShowFullHistory:
        tf = 3600.0
    else:
        if self.type == 0:
            tf = 60.0 # minutes
        else:
            tf = 3600.0 # hours

    return self.col.db.all("""\
        SELECT (CAST((revlog.id/1000 - :cut) / 86400.0 as int))/:chunk as day,
        sum(case when revlog.ivl>=21 and lastIvl < 21 then 1 else 0 end) as mcnt,
        sum(case when revlog.ivl<21 and lastIvl >= 21 then 1 else 0 end) as dcnt,
        sum(case when revlog.ivl>=365 and lastIvl < 365 then 1 else 0 end) as mcnt2,
        sum(case when revlog.ivl<365 and lastIvl >= 365 then 1 else 0 end) as dcnt2
        FROM revlog join cards on cards.id = revlog.cid
        %s
        GROUP BY day ORDER by day
    """ % lim, cut=self.col.sched.dayCutoff, tf=tf, chunk=chunk)

def getProgressCheckData(self):
    lim = self._revlogLimit()
    if lim:
        lim = "WHERE " + lim + " AND "
    else:
        lim = "WHERE "

    matured = self.col.db.scalar("""\
        SELECT  COUNT(DISTINCT cards.id)
        FROM    revlog join cards on cards.id = revlog.cid
        {lim}   cards.ivl >= 21
    """.format(lim=lim))
    known = self.col.db.scalar("""\
        SELECT  COUNT(DISTINCT cards.id)
        FROM    revlog join cards on cards.id = revlog.cid
        {lim}   cards.ivl >= 365
    """.format(lim=lim))
    dprint("checkdata: " + str(matured) + " | " + str(known))
    return matured, known

def accumdata(data):
    # chunkID == chunk*chunkID past today
    mature_good     = [] # (chunkID, newly matured)
    mature_fail     = [] # (chunkID, just forgotten)
    mature_accum    = [] # (chunkID, accumulated mature)
    total_matured   = [ 0, 0 ] # matured, forgotten

    known_good      = []
    known_fail      = []
    known_accum     = []
    total_known     = [ 0 ,0 ]

    # if there is no entry for the last chunk (deck not used recently) -> add an empty entry
    if data[-1][0] < 0:
        data.append( (0, 0, 0, 0, 0) )
    assert data[-1][0] == 0

    # XXX remove redundancy
    for chunkID, m, M, k, K in data: # lower case: mastered, upper case: failed
        mature_good.append( (chunkID,  m) )
        mature_fail.append( (chunkID, -M) )
        total_matured[0]    += m
        total_matured[1]    += M
        mature_accum.append( (chunkID, total_matured[0]-total_matured[1]) )

        known_good.append(  (chunkID,  k) )
        known_fail.append(  (chunkID, -K) )
        total_known[0]      += k
        total_known[1]      += K
        known_accum.append( (chunkID, total_known[0]-total_known[1]) )

    mature = {
            'good' : mature_good,
            'fail' : mature_fail,
            'accum': mature_accum,
            'total': total_matured
    }
    known = {
            'good' : known_good,
            'fail' : known_fail,
            'accum': known_accum,
            'total': total_known
    }

    return mature, known

def collectBadRevlogs(cid, bad_livl, bad_ivl):
    #if cid != 1312481332306: return None, None

    # the join removes revlogs whose cards have been deleted.
    # TODO shouldn't be such revlogs removed?
    sql='''\
        SELECT revlog.id, revlog.lastivl, revlog.ivl, cards.ivl
        FROM revlog JOIN cards ON cards.id = revlog.cid
        WHERE revlog.cid=:cid
        ORDER BY revlog.id; -- this is redundant?
    '''
    RID, LIVL, IVL, CIVL = range(0,4) # colums in select statement

    r = mw.col.db.all(sql, cid=cid)
    assert r # only cids from a join as above themselves should be passed into this function.

    livl = 0
    for e in r:
        if e[LIVL] != livl:
            bad_livl.append( (livl, e[RID]) ) # where and what to place
        livl = e[IVL]

    # also check ivl of last revlog entry of this card
    if e[IVL] != e[CIVL]:
        bad_ivl.append( (e[CIVL], e[RID]) )

