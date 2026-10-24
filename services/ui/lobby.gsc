// Ends the match when the web UI sets sv_tolobby 1 (End match): the scoreboard shows, then
// vote.gsc loads the next map, everyone stays connected.
// It also applies the cheat protected Fun dvars (fall damage), which the server ignores
// from server.cfg and rcon: the web UI saves a copy as sv_fun_<name>.
init()
{
	setDvar( "sv_tolobby", 0 );
	level thread watchToLobby();
	level thread applyCheatDvars();
}

watchToLobby()
{
	level endon( "game_ended" );

	while ( !getDvarInt( "sv_tolobby" ) )
		wait 0.25;

	setDvar( "sv_tolobby", 0 );
	maps\mp\gametypes\_gamelogic::forceEnd();
}

// re-checked every second: Save in the web UI changes them mid-match
applyCheatDvars()
{
	level endon( "game_ended" );

	names = strTok( "bg_fallDamageMinHeight bg_fallDamageMaxHeight", " " );
	for ( ;; )
	{
		foreach ( name in names )
		{
			// as a number: a string value reaches these float dvars as 0, which is out of range
			val = getDvarFloat( "sv_fun_" + name );
			if ( val >= 1 && getDvarFloat( name ) != val )
				setDvar( name, val );
		}
		wait 1;
	}
}
