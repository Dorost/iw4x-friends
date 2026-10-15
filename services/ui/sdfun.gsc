// Search & Destroy extras from the web UI's Fun panel (read when a round starts, S&D only).
// Every S&D round restarts the map, so this runs again each round.
// sv_sdroulette 1: every round gets a random modifier (knife round, snipers, moon, ...),
//   announced at the start; it replaces the Weapons mode for that round.
// sv_sdclutch 1: the last player alive on a team (that had 2 or more) gets radar,
//   infinite ammo and extra speed.
// sv_sdhunted 1: the bomb carrier shows on the enemy minimap and HUD, but runs faster.
// sv_sdrevive 1: a dead player leaves a green marker; a teammate standing on it for
//   3 seconds brings them back, once per player per round.
init()
{
	if ( getDvarInt( "sv_hangout" ) || getDvar( "g_gametype" ) != "sd" )
	{
		restorePhysics();
		return;
	}

	level.sdRoulette = getDvarInt( "sv_sdroulette" );
	level.sdClutch = getDvarInt( "sv_sdclutch" );
	level.sdHunted = getDvarInt( "sv_sdhunted" );
	level.sdRevive = getDvarInt( "sv_sdrevive" );
	level.sdRevived = [];
	level.sdModName = "";

	// physics from an earlier moon / speed round (a map change skips the round end)
	restorePhysics();
	if ( level.sdRoulette )
		pickModifier();
	if ( !level.sdRoulette && !level.sdClutch && !level.sdHunted && !level.sdRevive )
		return;

	level thread onConnect();
	level thread onRoundEnd();
	if ( level.sdClutch )
		level thread watchClutch();
	if ( level.sdHunted )
		level thread huntedBomb();
}

onConnect()
{
	for ( ;; )
	{
		level waittill( "connected", player );
		player thread onSpawn();
	}
}

onSpawn()
{
	self endon( "disconnect" );

	for ( ;; )
	{
		self waittill( "spawned_player" );
		self thread speedLoop();
		if ( level.sdRevive )
			self thread onDeath();
		if ( level.sdModName == "" )
			continue;
		// after the class loadout and weapons.gsc's Weapons mode
		wait 0.1;
		self giveModifier();
		if ( !isDefined( self.sdAnnounced ) )
		{
			self iPrintLnBold( "Round " + ( game[ "roundsPlayed" ] + 1 ) + ": " + level.sdModName );
			self.sdAnnounced = true;
		}
	}
}

onRoundEnd()
{
	level waittill( "game_ended" );
	restorePhysics();
}

// ---------- round roulette ----------

pickModifier()
{
	names = strTok( "Knife round,Snipers only,Pistols only,Shotguns only,Rocket round,Akimbo round,One in the chamber,Moon round,Speed round", "," );
	// never the same twice in a row
	for ( ;; )
	{
		i = randomInt( names.size );
		if ( !isDefined( game[ "sdLastMod" ] ) || game[ "sdLastMod" ] != i )
			break;
	}
	game[ "sdLastMod" ] = i;
	level.sdMod = i;
	level.sdModName = names[ i ];

	switch ( i )
	{
	case 0: list = "usp_tactical_mp"; break;
	case 1: list = "cheytac_mp barrett_mp wa2000_mp m21_mp"; break;
	case 2: list = "usp_mp beretta_mp deserteagle_mp coltanaconda_mp"; break;
	case 3: list = "spas12_mp aa12_mp striker_mp m1014_mp ranger_mp model1887_mp"; break;
	case 4: list = "rpg_mp at4_mp"; break;
	case 5: list = "glock_akimbo_mp tmp_akimbo_mp usp_akimbo_mp deserteagle_akimbo_mp model1887_akimbo_mp"; break;
	case 6: list = "deserteagle_mp"; break;
	default: list = ""; break;  // moon and speed rounds keep the class loadouts
	}
	level.sdModWeapons = strTok( list, " " );

	if ( i == 7 )
		setPhysics( "g_gravity", "200", "jump_height", "120" );
	else if ( i == 8 )
		setPhysics( "g_speed", "300", "player_sprintUnlimited", "1" );

	level thread modifierBanner();
}

// changes two physics dvars, keeping the old values in sv_sdrestore for restorePhysics()
setPhysics( a, aVal, b, bVal )
{
	setDvar( "sv_sdrestore", a + " " + getDvar( a ) + " " + b + " " + getDvar( b ) );
	setDvar( a, aVal );
	setDvar( b, bVal );
}

restorePhysics()
{
	saved = strTok( getDvar( "sv_sdrestore" ), " " );
	for ( i = 0; i + 1 < saved.size; i += 2 )
		setDvar( saved[ i ], saved[ i + 1 ] );
	setDvar( "sv_sdrestore", "" );
}

modifierBanner()
{
	banner = newHudElem();
	banner.alignX = "center";
	banner.alignY = "top";
	banner.horzAlign = "center";
	banner.vertAlign = "top";
	banner.y = 28;
	banner.font = "objective";
	banner.fontScale = 1.4;
	banner.color = ( 1, 0.8, 0.4 );
	banner.hideWhenInMenu = true;
	banner.archived = false;
	banner setText( level.sdModName );
}

giveModifier()
{
	if ( !level.sdModWeapons.size || !isAlive( self ) )
		return;

	weapon = level.sdModWeapons[ randomInt( level.sdModWeapons.size ) ];
	self takeAllWeapons();
	self giveWeapon( weapon, 0, level.sdMod == 5 );
	self giveMaxAmmo( weapon );
	self setSpawnWeapon( weapon );

	switch ( level.sdMod )
	{
	case 0:
		self setWeaponAmmoClip( weapon, 0 );
		self setWeaponAmmoStock( weapon, 0 );
		break;
	case 4:
		self thread refillAmmo();
		break;
	case 6:
		self setWeaponAmmoClip( weapon, 1 );
		self setWeaponAmmoStock( weapon, 0 );
		self thread bulletPerKill( weapon );
		break;
	}
}

// one in the chamber: every kill puts one more bullet in the magazine
bulletPerKill( weapon )
{
	self endon( "disconnect" );
	self endon( "death" );

	kills = self.pers[ "kills" ];
	for ( ;; )
	{
		wait 0.1;
		if ( self.pers[ "kills" ] > kills )
		{
			self setWeaponAmmoClip( weapon, self getWeaponAmmoClip( weapon ) + self.pers[ "kills" ] - kills );
			kills = self.pers[ "kills" ];
		}
	}
}

// the weapon in hand stays full, magazine included, as long as the player lives
refillAmmo()
{
	self endon( "disconnect" );
	self endon( "death" );

	for ( ;; )
	{
		wait 0.2;
		weapon = self getCurrentWeapon();
		if ( weapon != "none" && weapon != "usp_tactical_mp" )
		{
			self giveMaxAmmo( weapon );
			self setWeaponAmmoClip( weapon, weaponClipSize( weapon ) );
		}
	}
}

// ---------- speed (clutch and bomb carrier) ----------

// re-applied all the time: the game resets the speed on every weapon switch
speedLoop()
{
	self endon( "disconnect" );
	self endon( "death" );

	boosted = false;
	for ( ;; )
	{
		wait 0.25;
		factor = 1;
		if ( isDefined( self.sdClutch ) )
			factor *= 1.25;
		if ( level.sdHunted && isDefined( self.isBombCarrier ) && self.isBombCarrier )
			factor *= 1.2;
		if ( factor != 1 )
		{
			self setMoveSpeedScale( self.moveSpeedScaler * factor );
			boosted = true;
		}
		else if ( boosted )
		{
			self maps\mp\gametypes\_weapons::updateMoveSpeedScale( "primary" );
			boosted = false;
		}
	}
}

// ---------- clutch mode ----------

watchClutch()
{
	level endon( "game_ended" );

	maps\mp\_utility::gameFlagWait( "prematch_done" );
	most = [];
	most[ "allies" ] = 0;
	most[ "axis" ] = 0;
	for ( ;; )
	{
		wait 0.25;
		foreach ( team in strTok( "allies axis", " " ) )
		{
			alive = level.aliveCount[ team ];
			if ( alive > most[ team ] )
				most[ team ] = alive;
			if ( alive != 1 || most[ team ] < 2 || !level.aliveCount[ level.otherTeam[ team ] ] )
				continue;
			last = maps\mp\_utility::getLastLivingPlayer( team );
			if ( isDefined( last ) && !isDefined( last.sdClutch ) )
				last thread clutch();
		}
	}
}

clutch()
{
	self.sdClutch = true;
	foreach ( player in level.players )
		if ( player != self )
			player iPrintLnBold( self.name + " is clutching!" );
	self iPrintLnBold( "CLUTCH! Radar, endless ammo, extra speed" );
	self thread refillAmmo();
	self thread clutchRadar();
}

clutchRadar()
{
	self endon( "disconnect" );
	self endon( "death" );

	for ( ;; )
	{
		self.hasRadar = true;
		self.radarMode = "constant_radar";
		wait 0.5;
	}
}

// ---------- hunted bomb carrier ----------

// defenders see the bomb (and who carries it) on the minimap and as a HUD marker
huntedBomb()
{
	maps\mp\_utility::gameFlagWait( "prematch_done" );
	if ( !isDefined( level.sdBomb ) )
		return;  // multi bomb: everyone carries one
	level.sdBomb maps\mp\gametypes\_gameobjects::set2DIcon( "enemy", "waypoint_bomb" );
	level.sdBomb maps\mp\gametypes\_gameobjects::set3DIcon( "enemy", "waypoint_bomb" );
	level.sdBomb maps\mp\gametypes\_gameobjects::setVisibleTeam( "any" );
}

// ---------- revive ----------

onDeath()
{
	self endon( "disconnect" );

	self waittill( "death" );
	num = self getEntityNumber();
	if ( isDefined( level.sdRevived[ num ] ) || !level.teamBased )
		return;
	self thread reviveMarker( self.origin, self.angles, self.team );
}

reviveMarker( origin, angles, team )
{
	self endon( "disconnect" );
	level endon( "game_ended" );

	marker = newTeamHudElem( team );
	marker.x = origin[ 0 ];
	marker.y = origin[ 1 ];
	marker.z = origin[ 2 ] + 30;
	marker setShader( "objpoint_default", 10, 10 );
	marker.color = ( 0.3, 1, 0.4 );
	marker.alpha = 0.9;
	marker.archived = false;
	marker setWaypoint( true, false );
	level thread removeMarker( marker, self );

	foreach ( player in level.players )
		if ( player != self && player.team == team )
			player iPrintLn( self.name + " is down: stand on the green marker for 3s to revive" );

	reviver = undefined;
	held = 0;
	for ( ;; )
	{
		wait 0.25;
		if ( self.team != team )
		{
			self notify( "sd_marker_done" );
			return;
		}
		near = undefined;
		foreach ( player in level.players )
			if ( player != self && player.team == team && isAlive( player ) && distance( player.origin, origin ) < 64 )
				near = player;
		if ( !isDefined( near ) )
		{
			held = 0;
			continue;
		}
		if ( held == 0 )
			near iPrintLnBold( "Reviving " + self.name + "..." );
		held += 0.25;
		if ( held >= 3 )
		{
			reviver = near;
			break;
		}
	}

	level.sdRevived[ self getEntityNumber() ] = true;
	self notify( "sd_marker_done" );
	reviverName = reviver.name;
	// the killcam ends on its own; spawning in the middle of it breaks the player's view
	while ( isDefined( self.killcam ) )
		wait 0.1;
	self maps\mp\gametypes\_playerlogic::spawnPlayer();
	self setOrigin( origin );
	self setPlayerAngles( angles );
	foreach ( player in level.players )
		if ( player.team == team )
			player iPrintLnBold( reviverName + " revived " + self.name + "!" );
}

removeMarker( marker, player )
{
	level endon( "game_ended" );  // the next round's map restart clears it

	player common_scripts\utility::waittill_any( "sd_marker_done", "disconnect" );
	marker destroy();
}
