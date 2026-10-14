// Ends the match when the web UI sets sv_tolobby 1. On a lobby server that sends
// everyone back to the lobby, still connected (same as a match ending normally).
// In the waiting room match (sv_hangout 1, started by the web UI instead of idling in
// the lobby, so voice chat works) it shows a banner with the next map and mode, and
// nobody has weapons or takes damage.
init()
{
	setDvar( "sv_tolobby", 0 );
	level thread watchToLobby();

	if ( getDvarInt( "sv_hangout" ) )
	{
		level thread hangoutBanner();
		level thread hangoutWelcome();
		level thread hangoutNoDamage();
	}
}

watchToLobby()
{
	level endon( "game_ended" );

	while ( !getDvarInt( "sv_tolobby" ) )
		wait 0.25;

	setDvar( "sv_tolobby", 0 );
	maps\mp\gametypes\_gamelogic::forceEnd();
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
