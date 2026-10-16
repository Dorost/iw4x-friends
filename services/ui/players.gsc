// Per-player actions from the web UI's Players table. The UI sets
// sv_uicmd "<action> <client number> [argument]" over rcon; this runs it and clears it.
//   esp      toggle: markers on all enemies, visible through walls
//   radar    toggle: enemies always on the minimap
//   ammo     toggle: the weapon in hand never runs out, no reloading
//   clear    turn off wallhack, radar and ammo for the player
//   kill     kill the player
//   launch   throw the player into the air
//   up       teleport onto the roof / highest floor above the player
//   give     give a weapon (argument: weapon name)
// sv_uistate lists who has esp / radar / ammo on, for the UI: "<num>:<flags e r a> ..."
// The toggles also go into game["uiFlags"] (by guid), which survives the restart between
// rounds (S&D) but not a new map, and are turned back on when the player reconnects.
init()
{
	setDvar( "sv_uicmd", "" );
	setDvar( "sv_uistate", "" );
	if ( !isDefined( game[ "uiFlags" ] ) )
		game[ "uiFlags" ] = [];
	level thread watchCommands();
	level thread restoreToggles();
}

restoreToggles()
{
	level endon( "game_ended" );

	for ( ;; )
	{
		level waittill( "connected", player );
		flags = game[ "uiFlags" ][ player getGuid() ];
		if ( !isDefined( flags ) )
			continue;
		if ( isSubStr( flags, "e" ) )
			player toggleEsp();
		if ( isSubStr( flags, "r" ) )
			player toggleRadar();
		if ( isSubStr( flags, "a" ) )
			player toggleAmmo();
		updateState();
	}
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
		case "esp":
			player toggleEsp();
			break;
		case "radar":
			player toggleRadar();
			break;
		case "ammo":
			player toggleAmmo();
			break;
		case "clear":
			if ( isDefined( player.uiEsp ) && player.uiEsp )
				player toggleEsp();
			if ( isDefined( player.uiRadar ) && player.uiRadar )
				player toggleRadar();
			if ( isDefined( player.uiAmmo ) && player.uiAmmo )
				player toggleAmmo();
			break;
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
		game[ "uiFlags" ][ player getGuid() ] = player uiFlags();
		updateState();
	}
}

playerByNum( num )
{
	foreach ( player in level.players )
		if ( player getEntityNumber() == num )
			return player;
	return undefined;
}

uiFlags()
{
	flags = "";
	if ( isDefined( self.uiEsp ) && self.uiEsp )
		flags += "e";
	if ( isDefined( self.uiRadar ) && self.uiRadar )
		flags += "r";
	if ( isDefined( self.uiAmmo ) && self.uiAmmo )
		flags += "a";
	return flags;
}

updateState()
{
	state = "";
	foreach ( player in level.players )
	{
		flags = player uiFlags();
		if ( flags != "" )
			state += player getEntityNumber() + ":" + flags + " ";
	}
	setDvar( "sv_uistate", state );
}

// ---------- ESP ----------

toggleEsp()
{
	self.uiEsp = !( isDefined( self.uiEsp ) && self.uiEsp );
	self notify( "ui_esp_off" );
	if ( self.uiEsp )
	{
		self thread espLoop();
		self iPrintLn( "Wallhack ^2on" );
	}
	else
		self iPrintLn( "Wallhack ^1off" );
}

// keeps one marker per enemy, re-checked every half second (joins, leaves, team changes)
espLoop()
{
	self endon( "disconnect" );
	self endon( "ui_esp_off" );

	self.espIcons = [];
	self thread espCleanup();
	for ( ;; )
	{
		foreach ( target in level.players )
		{
			num = target getEntityNumber();
			show = target != self && isEnemy( target );
			if ( show && !isDefined( self.espIcons[ num ] ) )
				self.espIcons[ num ] = self espIcon( target );
			else if ( !show && isDefined( self.espIcons[ num ] ) )
			{
				self.espIcons[ num ] destroy();
				self.espIcons[ num ] = undefined;
			}
		}
		// targets that left
		foreach ( num in getArrayKeys( self.espIcons ) )
			if ( !isDefined( playerByNum( num ) ) )
			{
				self.espIcons[ num ] destroy();
				self.espIcons[ num ] = undefined;
			}
		wait 0.5;
	}
}

espCleanup()
{
	self waittill( "ui_esp_off" );
	foreach ( icon in self.espIcons )
		icon destroy();
	self.espIcons = [];
}

isEnemy( target )
{
	if ( !level.teamBased )
		return true;
	return isDefined( target.team ) && isDefined( self.team ) && target.team != self.team
		&& ( target.team == "allies" || target.team == "axis" );
}

espIcon( target )
{
	icon = newClientHudElem( self );
	icon setShader( "objpoint_default", 10, 10 );
	icon.color = ( 1, 0.3, 0.3 );
	icon.alpha = 0.9;
	icon.archived = false;
	icon setWaypoint( false, false );
	icon setTargetEnt( target );
	return icon;
}

// ---------- radar ----------

toggleRadar()
{
	self.uiRadar = !( isDefined( self.uiRadar ) && self.uiRadar );
	self notify( "ui_radar_off" );
	if ( self.uiRadar )
	{
		self thread radarLoop();
		self iPrintLn( "Radar ^2on" );
	}
	else
	{
		self.hasRadar = false;
		self iPrintLn( "Radar ^1off" );
	}
}

// re-applied all the time: UAV killstreaks reset the radar of everyone on a team
radarLoop()
{
	self endon( "disconnect" );
	self endon( "ui_radar_off" );

	for ( ;; )
	{
		self.hasRadar = true;
		self.radarMode = "constant_radar";
		wait 0.5;
	}
}

// ---------- infinite ammo ----------

toggleAmmo()
{
	self.uiAmmo = !( isDefined( self.uiAmmo ) && self.uiAmmo );
	self notify( "ui_ammo_off" );
	if ( self.uiAmmo )
	{
		self thread ammoLoop();
		self iPrintLn( "Infinite ammo ^2on" );
	}
	else
		self iPrintLn( "Infinite ammo ^1off" );
}

// tops up the weapon in hand, magazine included, through deaths and weapon switches
ammoLoop()
{
	self endon( "disconnect" );
	self endon( "ui_ammo_off" );

	for ( ;; )
	{
		weapon = self getCurrentWeapon();
		if ( weapon != "none" )
		{
			self giveMaxAmmo( weapon );
			self setWeaponAmmoClip( weapon, weaponClipSize( weapon ) );
		}
		wait 0.2;
	}
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
