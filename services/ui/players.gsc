// Per-player actions from the web UI's Players table. The UI sets
// sv_uicmd "<action> <client number> [argument]" over rcon; this runs it and clears it.
//   kill     kill the player
//   launch   throw the player into the air
//   up       teleport onto the roof / highest floor above the player
//   give     give a weapon (argument: weapon name)
init()
{
	setDvar( "sv_uicmd", "" );
	level thread watchCommands();
}

watchCommands()
{
	level endon( "game_ended" );

	for ( ;; )
	{
		wait 0.1;
		cmd = getDvar( "sv_uicmd" );
		if ( cmd == "" )
			continue;
		setDvar( "sv_uicmd", "" );

		args = strTok( cmd, " " );
		if ( args.size < 2 )
			continue;
		player = playerByNum( int( args[ 1 ] ) );
		if ( !isDefined( player ) )
			continue;

		switch ( args[ 0 ] )
		{
		case "kill":
			if ( isAlive( player ) )
				player suicide();
			break;
		case "launch":
			if ( isAlive( player ) )
				player setVelocity( player getVelocity() + ( 0, 0, 900 ) );
			break;
		case "up":
			if ( isAlive( player ) )
				player teleportUp();
			break;
		case "give":
			if ( isAlive( player ) && args.size > 2 )
				player giveGun( args[ 2 ] );
			break;
		}
	}
}

playerByNum( num )
{
	foreach ( player in level.players )
		if ( player getEntityNumber() == num )
			return player;
	return undefined;
}

// ---------- teleport / weapons ----------

// onto whatever is above: the first ceiling up, then down onto its top surface
teleportUp()
{
	far = 100000;
	start = self.origin + ( 0, 0, 40 );
	ceiling = physicsTrace( start, start + ( 0, 0, far ), false, self );
	above = physicsTrace( ceiling + ( 0, 0, 1 ), ceiling + ( 0, 0, far ), false, self );
	self setOrigin( playerPhysicsTrace( above, ceiling - ( 0, 0, far ), false, self ) );
}

giveGun( weapon )
{
	self giveWeapon( weapon );
	self giveMaxAmmo( weapon );
	self switchToWeapon( weapon );
}
