from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
from datetime import datetime

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database initialization
def init_db():
    conn = sqlite3.connect('cricket.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS matches
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  team1 TEXT NOT NULL,
                  team2 TEXT NOT NULL,
                  overs INTEGER NOT NULL,
                  current_inning INTEGER DEFAULT 1,
                  status TEXT DEFAULT 'in_progress',
                  winner TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS innings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  match_id INTEGER,
                  inning_number INTEGER,
                  batting_team TEXT,
                  bowling_team TEXT,
                  total_runs INTEGER DEFAULT 0,
                  total_wickets INTEGER DEFAULT 0,
                  total_balls INTEGER DEFAULT 0,
                  extras INTEGER DEFAULT 0,
                  FOREIGN KEY (match_id) REFERENCES matches(id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS batsmen
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  inning_id INTEGER,
                  name TEXT NOT NULL,
                  runs INTEGER DEFAULT 0,
                  balls INTEGER DEFAULT 0,
                  fours INTEGER DEFAULT 0,
                  sixes INTEGER DEFAULT 0,
                  is_out BOOLEAN DEFAULT 0,
                  out_type TEXT,
                  is_striker BOOLEAN DEFAULT 0,
                  FOREIGN KEY (inning_id) REFERENCES innings(id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS bowlers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  inning_id INTEGER,
                  name TEXT NOT NULL,
                  overs INTEGER DEFAULT 0,
                  balls INTEGER DEFAULT 0,
                  runs_given INTEGER DEFAULT 0,
                  wickets INTEGER DEFAULT 0,
                  maidens INTEGER DEFAULT 0,
                  is_current BOOLEAN DEFAULT 0,
                  FOREIGN KEY (inning_id) REFERENCES innings(id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS balls
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  inning_id INTEGER,
                  over_number INTEGER,
                  ball_number INTEGER,
                  runs INTEGER DEFAULT 0,
                  is_wicket BOOLEAN DEFAULT 0,
                  is_extra BOOLEAN DEFAULT 0,
                  extra_type TEXT,
                  batsman_id INTEGER,
                  bowler_id INTEGER,
                  FOREIGN KEY (inning_id) REFERENCES innings(id))''')
    
    conn.commit()
    conn.close()

init_db()

# Pydantic models
class MatchCreate(BaseModel):
    team1: str
    team2: str
    overs: int

class BatsmanCreate(BaseModel):
    name: str
    is_striker: bool = False

class BowlerCreate(BaseModel):
    name: str

class BallUpdate(BaseModel):
    runs: int
    is_wicket: bool = False
    wicket_type: Optional[str] = None
    is_extra: bool = False
    extra_type: Optional[str] = None

# Helper functions
def get_db():
    conn = sqlite3.connect('cricket.db')
    conn.row_factory = sqlite3.Row
    return conn

# API Endpoints
@app.post("/api/matches")
async def create_match(match: MatchCreate):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("INSERT INTO matches (team1, team2, overs) VALUES (?, ?, ?)",
              (match.team1, match.team2, match.overs))
    match_id = c.lastrowid
    
    # Create first inning
    c.execute("INSERT INTO innings (match_id, inning_number, batting_team, bowling_team) VALUES (?, ?, ?, ?)",
              (match_id, 1, match.team1, match.team2))
    
    conn.commit()
    conn.close()
    
    return {"match_id": match_id, "message": "Match created successfully"}

@app.get("/api/matches/{match_id}")
async def get_match(match_id: int):
    conn = get_db()
    c = conn.cursor()
    
    match = c.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    innings = c.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY inning_number", 
                       (match_id,)).fetchall()
    
    result = {
        "match": dict(match),
        "innings": []
    }
    
    for inning in innings:
        inning_dict = dict(inning)
        
        batsmen = c.execute("SELECT * FROM batsmen WHERE inning_id = ?", 
                           (inning['id'],)).fetchall()
        bowlers = c.execute("SELECT * FROM bowlers WHERE inning_id = ?", 
                           (inning['id'],)).fetchall()
        balls = c.execute("SELECT * FROM balls WHERE inning_id = ? ORDER BY over_number, ball_number", 
                         (inning['id'],)).fetchall()
        
        inning_dict['batsmen'] = [dict(b) for b in batsmen]
        inning_dict['bowlers'] = [dict(b) for b in bowlers]
        inning_dict['balls'] = [dict(b) for b in balls]
        
        result['innings'].append(inning_dict)
    
    conn.close()
    return result

@app.post("/api/innings/{inning_id}/batsmen")
async def add_batsman(inning_id: int, batsman: BatsmanCreate):
    conn = get_db()
    c = conn.cursor()
    
    # If striker, unset other strikers
    if batsman.is_striker:
        c.execute("UPDATE batsmen SET is_striker = 0 WHERE inning_id = ?", (inning_id,))
    
    c.execute("INSERT INTO batsmen (inning_id, name, is_striker) VALUES (?, ?, ?)",
              (inning_id, batsman.name, batsman.is_striker))
    
    conn.commit()
    conn.close()
    
    return {"message": "Batsman added successfully"}

@app.post("/api/innings/{inning_id}/bowlers")
async def add_bowler(inning_id: int, bowler: BowlerCreate):
    conn = get_db()
    c = conn.cursor()
    
    # Set current bowler
    c.execute("UPDATE bowlers SET is_current = 0 WHERE inning_id = ?", (inning_id,))
    c.execute("INSERT INTO bowlers (inning_id, name, is_current) VALUES (?, ?, ?)",
              (inning_id, bowler.name, True))
    
    conn.commit()
    conn.close()
    
    return {"message": "Bowler added successfully"}

@app.post("/api/innings/{inning_id}/balls")
async def add_ball(inning_id: int, ball: BallUpdate):
    conn = get_db()
    c = conn.cursor()
    
    # Get current inning details
    inning = c.execute("SELECT * FROM innings WHERE id = ?", (inning_id,)).fetchone()
    
    # Get striker batsman
    striker = c.execute("SELECT * FROM batsmen WHERE inning_id = ? AND is_striker = 1", 
                       (inning_id,)).fetchone()
    if not striker:
        conn.close()
        raise HTTPException(status_code=400, detail="No striker batsman found")
    
    # Get current bowler
    bowler = c.execute("SELECT * FROM bowlers WHERE inning_id = ? AND is_current = 1", 
                      (inning_id,)).fetchone()
    if not bowler:
        conn.close()
        raise HTTPException(status_code=400, detail="No current bowler found")
    
    # Calculate over and ball number
    total_balls = inning['total_balls']
    over_number = total_balls // 6
    ball_number = total_balls % 6
    
    # Add ball record
    c.execute("""INSERT INTO balls (inning_id, over_number, ball_number, runs, is_wicket, 
                 is_extra, extra_type, batsman_id, bowler_id) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
              (inning_id, over_number, ball_number, ball.runs, ball.is_wicket, 
               ball.is_extra, ball.extra_type, striker['id'], bowler['id']))
    
    # Update batsman stats
    if not ball.is_extra or ball.extra_type in ['lb', 'b']:
        c.execute("UPDATE batsmen SET balls = balls + 1 WHERE id = ?", (striker['id'],))
    
    if not ball.is_extra:
        c.execute("UPDATE batsmen SET runs = runs + ? WHERE id = ?", (ball.runs, striker['id']))
        if ball.runs == 4:
            c.execute("UPDATE batsmen SET fours = fours + 1 WHERE id = ?", (striker['id'],))
        elif ball.runs == 6:
            c.execute("UPDATE batsmen SET sixes = sixes + 1 WHERE id = ?", (striker['id'],))
    
    # Update bowler stats
    if not ball.is_extra or ball.extra_type in ['lb', 'b']:
        c.execute("UPDATE bowlers SET balls = balls + 1 WHERE id = ?", (bowler['id'],))
        # Update overs
        new_balls = bowler['balls'] + 1
        c.execute("UPDATE bowlers SET overs = ? WHERE id = ?", (new_balls // 6, bowler['id']))
    
    c.execute("UPDATE bowlers SET runs_given = runs_given + ? WHERE id = ?", 
              (ball.runs, bowler['id']))
    
    if ball.is_wicket:
        c.execute("UPDATE bowlers SET wickets = wickets + 1 WHERE id = ?", (bowler['id'],))
        c.execute("UPDATE batsmen SET is_out = 1, out_type = ? WHERE id = ?", 
                  (ball.wicket_type, striker['id']))
    
    # Update inning stats
    if not ball.is_extra or ball.extra_type in ['lb', 'b']:
        c.execute("UPDATE innings SET total_balls = total_balls + 1 WHERE id = ?", (inning_id,))
    
    c.execute("UPDATE innings SET total_runs = total_runs + ? WHERE id = ?", 
              (ball.runs, inning_id))
    
    if ball.is_extra:
        c.execute("UPDATE innings SET extras = extras + ? WHERE id = ?", (ball.runs, inning_id))
    
    if ball.is_wicket:
        c.execute("UPDATE innings SET total_wickets = total_wickets + 1 WHERE id = ?", (inning_id,))
    
    conn.commit()
    conn.close()
    
    return {"message": "Ball recorded successfully"}

@app.put("/api/batsmen/{batsman_id}/striker")
async def toggle_striker(batsman_id: int):
    conn = get_db()
    c = conn.cursor()
    
    batsman = c.execute("SELECT * FROM batsmen WHERE id = ?", (batsman_id,)).fetchone()
    if not batsman:
        raise HTTPException(status_code=404, detail="Batsman not found")
    
    # Unset all strikers in this inning
    c.execute("UPDATE batsmen SET is_striker = 0 WHERE inning_id = ?", (batsman['inning_id'],))
    # Set this batsman as striker
    c.execute("UPDATE batsmen SET is_striker = 1 WHERE id = ?", (batsman_id,))
    
    conn.commit()
    conn.close()
    
    return {"message": "Striker updated"}

@app.post("/api/matches/{match_id}/next-inning")
async def next_inning(match_id: int):
    conn = get_db()
    c = conn.cursor()
    
    match = c.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if match['current_inning'] >= 2:
        raise HTTPException(status_code=400, detail="Match already has 2 innings")
    
    # Create second inning
    c.execute("""INSERT INTO innings (match_id, inning_number, batting_team, bowling_team) 
                 VALUES (?, ?, ?, ?)""",
              (match_id, 2, match['team2'], match['team1']))
    
    c.execute("UPDATE matches SET current_inning = 2 WHERE id = ?", (match_id,))
    
    conn.commit()
    conn.close()
    
    return {"message": "Second inning started"}

@app.put("/api/matches/{match_id}/complete")
async def complete_match(match_id: int, winner: str = Query(...)):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("UPDATE matches SET status = 'completed', winner = ? WHERE id = ?", 
              (winner, match_id))
    
    conn.commit()
    conn.close()
    
    return {"message": "Match completed"}

@app.get("/api/matches")
async def list_matches():
    conn = get_db()
    c = conn.cursor()
    
    matches = c.execute("SELECT * FROM matches ORDER BY created_at DESC").fetchall()
    
    conn.close()
    return [dict(m) for m in matches]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)