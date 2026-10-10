// Ends the match when the web UI sets sv_tolobby 1. On a lobby server that sends
// everyone back to the lobby, still connected (same as a match ending normally).
init()
{
	setDvar( "sv_tolobby", 0 );
	level thread watchToLobby();
}

watchToLobby()
{
	level endon( "game_ended" );

	while ( !getDvarInt( "sv_tolobby" ) )
		wait 0.25;

	setDvar( "sv_tolobby", 0 );
	maps\mp\gametypes\_gamelogic::forceEnd();
}
