// Ends the match when the web UI sets sv_tolobby 1. On a lobby server that sends
// everyone back to the lobby, still connected (same as a match ending normally).
// In the waiting room match (sv_hangout 1, started by the web UI instead of idling in
// the lobby, so voice chat works) it shows a banner with the next map and mode, and
// nobody has weapons or takes damage.
// A match that ends by itself (score or time limit) shows the scoreboard, then switches
// straight to the waiting room instead of the lobby (when the web UI has it on).
// It also applies the cheat protected Fun dvars (fall damage), which the server ignores
// from server.cfg and rcon: the web UI saves a copy as sv_fun_<name>.
init()
{
	setDvar( "sv_tolobby", 0 );
	level thread watchToLobby();
	level thread applyCheatDvars();

	// sv_hangout left on in a real match (it's only for the waiting room's map and mode, see
	// endToHangout) would take everyone's guns: clear it. This runs before sdfun.gsc and
	// weapons.gsc read it, scripts start in name order.
	if ( getDvarInt( "sv_hangout" ) && ( getDvar( "mapname" ) != "mp_rust" || getDvar( "g_gametype" ) != "dm" ) )
		setDvar( "sv_hangout", 0 );

	if ( getDvarInt( "sv_hangout" ) )
	{
		level thread hangoutBanner();
		level thread hangoutWelcome();
		level thread hangoutNoDamage();
	}
	else if ( getDvar( "sv_hangout_enabled" ) != "0" )
		level thread endToHangout();
}

watchToLobby()
{
	level endon( "game_ended" );

	while ( !getDvarInt( "sv_tolobby" ) )
		wait 0.25;

	setDvar( "sv_tolobby", 0 );
	maps\mp\gametypes\_gamelogic::forceEnd();
}

// same commands as start_hangout( from_match=True ) in app.py (HANGOUT_MAP, HANGOUT_MODE)
endToHangout()
{
	level waittill( "spawning_intermission" );  // final scoreboard is up

	// endGame calls exitLevel (back to the lobby) at least 4 s after the scoreboard shows,
	// plus the intermission outside matchmaking: switch just before that
	delay = 3.5;
	if ( !maps\mp\_utility::matchMakingGame() )
	{
		if ( getDvarInt( "party_host" ) )
			delay += 10;
		else
			delay += level.intermissionTime;
	}
	wait delay;

	cmds = strTok( "ui_mapname mp_rust;ui_gametype dm;g_gametype dm;set scr_dm_timelimit 0;set scr_dm_scorelimit 0;set bots_manage_fill 0;set sv_hangout 1;map mp_rust", ";" );
	foreach ( cmd in cmds )
		exec( cmd );
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

hangoutBanner()
{
	level endon( "game_ended" );

	title = newHudElem();
	title.alignX = "center";
	title.alignY = "top";
	title.horzAlign = "center";
	title.vertAlign = "top";
	title.y = 28;
	title.font = "objective";
	title.fontScale = 1.8;
	title.color = ( 0.55, 0.85, 1 );
	title.glowColor = ( 0.2, 0.45, 0.8 );
	title.glowAlpha = 0.6;
	title.hideWhenInMenu = true;
	title.archived = false;
	title setText( "WAITING ROOM" );

	next = newHudElem();
	next.alignX = "center";
	next.alignY = "top";
	next.horzAlign = "center";
	next.vertAlign = "top";
	next.y = 50;
	next.font = "objective";
	next.fontScale = 1.3;
	next.hideWhenInMenu = true;
	next.archived = false;

	hint = newHudElem();
	hint.alignX = "center";
	hint.alignY = "top";
	hint.horzAlign = "center";
	hint.vertAlign = "top";
	hint.y = 68;
	hint.font = "default";
	hint.fontScale = 1.2;
	hint.color = ( 0.75, 0.75, 0.75 );
	hint.hideWhenInMenu = true;
	hint.archived = false;
	hint setText( "No guns, voice chat is on - hang out while the host starts the match" );

	// the web UI updates sv_hangout_msg when the host picks another map or mode
	shown = "";
	for ( ;; )
	{
		msg = getDvar( "sv_hangout_msg" );
		if ( msg != shown )
		{
			next setText( msg );
			shown = msg;
		}
		wait 1;
	}
}

hangoutWelcome()
{
	level endon( "game_ended" );

	for ( ;; )
	{
		level waittill( "connected", player );
		player thread welcome();
	}
}

welcome()
{
	self endon( "disconnect" );
	level endon( "game_ended" );

	greeted = false;
	for ( ;; )
	{
		self waittill( "spawned_player" );
		// no guns or grenades: taken after every spawn, once the class loadout is given
		wait 0.05;
		self takeAllWeapons();
		if ( !greeted )
		{
			self iPrintLnBold( "Welcome to the waiting room, " + self.name );
			greeted = true;
		}
	}
}

// nobody can hurt anyone in the waiting room (weapons, explosives, killstreaks, falling).
// Re-applied every second: the gametype sets its own damage callback during start-up
hangoutNoDamage()
{
	level endon( "game_ended" );

	for ( ;; )
	{
		level.callbackPlayerDamage = ::noDamage;
		wait 1;
	}
}

noDamage( eInflictor, eAttacker, iDamage, iDFlags, sMeansOfDeath, sWeapon, vPoint, vDir, sHitLoc, psOffsetTime )
{
}
