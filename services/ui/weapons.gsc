// Weapon modes from the web UI's Fun panel (read when a match starts).
// sv_funweapons: after every spawn the class loadout is swapped for a weapon of the mode,
// picked at random per spawn.
//   0 classes, 1 knife only, 2 snipers, 3 pistols, 4 shotguns, 5 launchers (ammo refills),
//   6 riot shields, 7 roulette (any weapon), 8 akimbo, 9 one in the chamber (Deagle with
//   one bullet, one more per kill), 10 AC-130 cannons (ammo refills), 11 semtex (knife
//   plus semtex that refills), 12 bomberman (knife plus C4 or claymores, refill), 13 throwing
//   knives (refill), 14 noob tubes (Thumpers, ammo refills), 15 gun game (every kill moves
//   you to the next weapon of level.gunGame, a kill with the last one wins), 16 gun game
//   extended (same rules, the ladder is the whole MW2 arsenal, edit it in init(); the last
//   level is a throwing knife only, no weapon in hand, and only a throwing knife kill wins)
// sv_funammo 1: the weapon in hand never runs out of ammo, no reloading.
// sv_funlottery N: every spawn has a 1 in N chance to come with an extra AC-130 cannon.
// sv_funrotate N: one player at a time holds the AC-130 cannon for N seconds (or until they
// die), then it moves to another random living player.
// sv_funpotato N: one random player carries a bomb that explodes after N seconds; a kill
// passes it to someone else.
// sv_funairkill N: every Nth kill hands out a random air killstreak (level.airStreaks); they
// stack up in the killstreak slot like care package rewards.
init()
{
	level.funWeaponMode = getDvarInt( "sv_funweapons" );
	level.funAmmo = getDvarInt( "sv_funammo" );
	level.funLottery = getDvarInt( "sv_funlottery" );
	level.funRotate = getDvarInt( "sv_funrotate" );
	level.funPotato = getDvarInt( "sv_funpotato" );
	level.funAirKill = getDvarInt( "sv_funairkill" );
	if ( !level.funWeaponMode && !level.funAmmo && !level.funLottery && !level.funRotate && !level.funPotato
		&& !level.funAirKill )
		return;

	snipers = "cheytac_mp barrett_mp wa2000_mp m21_mp";
	pistols = "usp_mp beretta_mp deserteagle_mp coltanaconda_mp";
	shotguns = "spas12_mp aa12_mp striker_mp m1014_mp ranger_mp model1887_mp";
	rifles = "m4_mp ak47_mp famas_mp fal_mp scar_mp tavor_mp masada_mp fn2000_mp m16_mp";
	smgs = "mp5k_mp ump45_mp kriss_mp p90_mp uzi_mp pp2000_mp glock_mp tmp_mp beretta393_mp";
	lmgs = "sa80_mp rpd_mp mg4_mp aug_mp m240_mp";
	akimbo = "glock_akimbo_mp pp2000_akimbo_mp tmp_akimbo_mp beretta393_akimbo_mp model1887_akimbo_mp ranger_akimbo_mp usp_akimbo_mp deserteagle_akimbo_mp coltanaconda_akimbo_mp";

	switch ( level.funWeaponMode )
	{
	case 0: list = ""; break;
	case 1: list = "usp_tactical_mp"; break;  // tactical knife, no bullets
	case 2: list = snipers; break;
	case 3: list = pistols; break;
	case 4: list = shotguns; break;
	case 5: list = "rpg_mp at4_mp"; break;
	case 6: list = "riotshield_mp"; break;
	case 8: list = akimbo; break;
	case 9: list = "deserteagle_mp"; break;
	case 10: list = "ac130_105mm_mp"; break;  // the gunship's 105mm cannon in hand
	case 11:
	case 12:
	case 13: list = "usp_tactical_mp"; break;  // knife in hand, the fun is the offhand item
	case 14: list = "m79_mp"; break;  // Thumper grenade launcher
	case 15:
	case 16: list = "usp_mp"; break;  // not used: gun game hands out level.gunGame in order
	default: list = snipers + " " + pistols + " " + shotguns + " " + rifles + " " + smgs + " " + lmgs + " rpg_mp riotshield_mp"; break;
	}
	level.funWeapons = strTok( list, " " );
	level.gunGame = strTok( "usp_mp deserteagle_mp ump45_mp kriss_mp p90_mp m4_mp ak47_mp scar_mp aa12_mp spas12_mp m240_mp barrett_mp cheytac_mp rpg_mp ac130_105mm_mp usp_tactical_mp", " " );
	if ( level.funWeaponMode == 16 )
	{
		// one kill per level, a kill with the last one wins; edit the order here
		level.gunGame = strTok(
			"usp_mp beretta_mp coltanaconda_mp deserteagle_mp "                              // pistols
			+ "pp2000_mp glock_mp beretta393_mp tmp_mp "                                     // machine pistols
			+ "mp5k_mp uzi_mp ump45_mp kriss_mp p90_mp "                                     // SMGs
			+ "m4_mp famas_mp scar_mp tavor_mp fal_mp m16_mp masada_mp fn2000_mp ak47_mp "   // assault rifles
			+ "ranger_mp model1887_mp striker_mp m1014_mp aa12_mp spas12_mp "                // shotguns
			+ "sa80_mp rpd_mp mg4_mp aug_mp m240_mp "                                        // LMGs
			+ "m21_mp wa2000_mp barrett_mp cheytac_mp "                                      // snipers
			+ "m79_mp at4_mp rpg_mp "                                                        // launchers
			+ "model1887_akimbo_mp riotshield_mp ac130_105mm_mp usp_tactical_mp "            // finishers, knife
			+ "throwingknife_mp", " " );                                                     // throwing knife only, last
		// TEST: 5 levels (3 pistols, knife, throwing knife) to try the last levels with bots; drop before release
		level.gunGame = strTok( "usp_mp beretta_mp coltanaconda_mp usp_tactical_mp throwingknife_mp", " " );
		// 45 levels: the stock score limit (30 kills in Free-for-all) would end the match first
		if ( getDvar( "g_gametype" ) == "dm" || getDvar( "g_gametype" ) == "war" )
			setDvar( "scr_" + getDvar( "g_gametype" ) + "_scorelimit", 0 );
		// tells gunGameLoop which kills were throwing knife kills (init runs after the gametype's
		// main has set up the stock callbacks)
		level.gunPrevKilled = level.callbackPlayerKilled;
		level.callbackPlayerKilled = ::gunGameKilled;
	}
	level thread onConnect();
	if ( level.funPotato )
		level thread hotPotato();
	// air killstreaks for air support per kill; names for the announcement
	level.airStreaks = strTok( "predator_missile harrier_airstrike helicopter helicopter_flares helicopter_minigun ac130", " " );
	level.airNames = strTok( "Predator missile,Harrier strike,Attack helicopter,Pave Low,Chopper gunner,AC-130", "," );
	// pointless when everyone already has the cannon
	if ( level.funRotate && level.funWeaponMode != 10 )
		level thread rotateCannon();
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
		// after the class loadout is given
		wait 0.05;
		if ( level.funWeapons.size )
			self giveFunWeapon();
		// pointless when everyone already has the cannon
		if ( level.funLottery && level.funWeaponMode != 10 && randomInt( level.funLottery ) == 0 )
			self giveLotteryCannon();
		if ( level.funAirKill )
			self thread airPerKill();
		// no endless ammo for modes that live off having none
		if ( level.funAmmo && level.funWeaponMode != 1 && level.funWeaponMode != 9 )
			self thread refillAmmo();
	}
}

giveFunWeapon()
{
	if ( level.funWeaponMode == 15 || level.funWeaponMode == 16 )
	{
		if ( !isDefined( self.gunLevel ) )
			self.gunLevel = 0;
		self giveGunLevel( true );
		self thread gunGameLoop();
		return;
	}
	weapon = level.funWeapons[ randomInt( level.funWeapons.size ) ];
	self takeAllWeapons();
	self giveWeapon( weapon, 0, level.funWeaponMode == 8 || isSubStr( weapon, "_akimbo" ) );
	self giveMaxAmmo( weapon );
	self setSpawnWeapon( weapon );

	switch ( level.funWeaponMode )
	{
	case 1:
		self setWeaponAmmoClip( weapon, 0 );
		self setWeaponAmmoStock( weapon, 0 );
		break;
	case 5:
	case 10:
	case 14:
		self thread refillAmmo();
		break;
	case 11:
		self emptyKnife( weapon );
		self giveOffhand( "semtex_mp", "other" );
		break;
	case 12:
		self emptyKnife( weapon );
		if ( randomInt( 2 ) )
			self giveOffhand( "c4_mp", "other" );
		else
			self giveOffhand( "claymore_mp", "other" );
		break;
	case 13:
		self emptyKnife( weapon );
		self giveOffhand( "throwingknife_mp", "throwingknife" );
		break;
	case 9:
		self setWeaponAmmoClip( weapon, 1 );
		self setWeaponAmmoStock( weapon, 0 );
		self thread bulletPerKill( weapon );
		break;
	}
}

// the knife-only USP: no bullets, melee only
emptyKnife( weapon )
{
	self setWeaponAmmoClip( weapon, 0 );
	self setWeaponAmmoStock( weapon, 0 );
}

// a lethal (semtex, C4, claymore, throwing knife) that refills itself while the player lives:
// every second, or with a delay, that many seconds after the last one is thrown
giveOffhand( item, offhandClass, delay )
{
	self setOffhandPrimaryClass( offhandClass );
	self giveWeapon( item );
	self giveMaxAmmo( item );
	if ( isDefined( delay ) )
		self thread refillAfterThrow( item, delay );
	else
		self thread refillOffhand( item );
}

refillOffhand( item )
{
	self endon( "disconnect" );
	self endon( "death" );

	for ( ;; )
	{
		wait 1;
		self giveMaxAmmo( item );
		self setWeaponAmmoClip( item, weaponClipSize( item ) );
	}
}

refillAfterThrow( item, delay )
{
	self endon( "disconnect" );
	self endon( "death" );

	for ( ;; )
	{
		wait 0.1;
		if ( self getAmmoCount( item ) )
			continue;
		wait delay;
		self giveMaxAmmo( item );
		self setWeaponAmmoClip( item, weaponClipSize( item ) );
	}
}

// gun game: every kill hands out the next weapon of level.gunGame; a kill with the last wins
gunGameLoop()
{
	self endon( "disconnect" );
	self endon( "death" );

	self.gunKnifeKill = undefined;  // a knife still flying when the player died
	kills = self.pers[ "kills" ];
	for ( ;; )
	{
		wait 0.1;
		if ( self.pers[ "kills" ] <= kills )
			continue;
		kills = self.pers[ "kills" ];
		knifeKill = isDefined( self.gunKnifeKill );
		self.gunKnifeKill = undefined;
		if ( level.gunGame[ self.gunLevel ] == "throwingknife_mp" && !knifeKill )
		{
			self iPrintLnBold( "Only a throwing knife kill counts" );
			continue;
		}
		self.gunLevel++;
		if ( self.gunLevel >= level.gunGame.size )
		{
			self gunGameWin();
			return;
		}
		self giveGunLevel( false );
		msg = "Gun game: level " + ( self.gunLevel + 1 ) + " of " + level.gunGame.size;
		if ( level.gunGame[ self.gunLevel ] == "throwingknife_mp" )
			msg = msg + ", a throwing knife kill wins";
		self iPrintLnBold( msg );
	}
}

// the weapon of self.gunLevel, in hand right away on spawn; the throwing knife level has no
// weapon in hand, only a throwing knife that comes back 3 seconds after each throw
giveGunLevel( spawned )
{
	weapon = level.gunGame[ self.gunLevel ];
	self takeAllWeapons();
	if ( weapon == "throwingknife_mp" )
	{
		self giveOffhand( weapon, "throwingknife", 3 );
		self thread knifeCrosshair();
		return;
	}
	self giveWeapon( weapon, 0, isSubStr( weapon, "_akimbo" ) );
	self giveMaxAmmo( weapon );
	if ( weapon == "usp_tactical_mp" )
		self emptyKnife( weapon );
	if ( spawned )
		self setSpawnWeapon( weapon );
	else
		self switchToWeapon( weapon );
}

// no weapon in hand draws no crosshair: a hip fire one for the throwing knife level, until the
// player dies or the match ends
knifeCrosshair()
{
	arms = [];
	arms[ 0 ] = self crosshairArm( -7, 0, 6, 1 );
	arms[ 1 ] = self crosshairArm( 7, 0, 6, 1 );
	arms[ 2 ] = self crosshairArm( 0, -7, 1, 6 );
	arms[ 3 ] = self crosshairArm( 0, 7, 1, 6 );
	while ( isDefined( self ) && isAlive( self ) && !level.gameEnded )
		wait 0.05;
	foreach ( arm in arms )
		if ( isDefined( arm ) )
			arm destroy();
}

// one arm of the crosshair: x, y from the screen center, in 640x480 HUD units
crosshairArm( x, y, width, height )
{
	arm = newClientHudElem( self );
	arm.horzAlign = "center";
	arm.vertAlign = "middle";
	arm.alignX = "center";
	arm.alignY = "middle";
	arm.x = x;
	arm.y = y;
	arm.alpha = 0.8;
	arm.archived = false;
	arm.hideWhenInMenu = true;
	arm setShader( "white", width, height );
	return arm;
}

// marks a throwing knife kill for gunGameLoop, before the stock callback counts the kill
gunGameKilled( eInflictor, attacker, iDamage, sMeansOfDeath, sWeapon, vDir, sHitLoc, timeOffset, deathAnimDuration )
{
	if ( sWeapon == "throwingknife_mp" && isDefined( attacker ) && isPlayer( attacker ) && attacker != self
		&& ( !level.teamBased || attacker.team != self.team ) )
		attacker.gunKnifeKill = true;
	self [[ level.gunPrevKilled ]]( eInflictor, attacker, iDamage, sMeansOfDeath, sWeapon, vDir, sHitLoc, timeOffset, deathAnimDuration );
}

gunGameWin()
{
	if ( isDefined( level.gunGameWon ) )
		return;
	level.gunGameWon = true;
	foreach ( player in level.players )
		player iPrintLnBold( self.name + " won gun game!" );
	winner = self;
	if ( level.teamBased )
		winner = self.team;
	level thread maps\mp\gametypes\_gamelogic::endGame( winner, game[ "strings" ][ "score_limit_reached" ] );
}

// hot potato: one carrier at a time with a bomb timer; a kill passes the bomb to someone
// else, the timer running out blows the carrier up (the AC-130 shell makes the explosion)
hotPotato()
{
	level endon( "game_ended" );

	last = undefined;
	for ( ;; )
	{
		candidates = [];
		foreach ( player in level.players )
			if ( isAlive( player ) && ( !isDefined( last ) || player != last ) )
				candidates[ candidates.size ] = player;
		if ( !candidates.size )
		{
			last = undefined;  // a lone player may get it again
			wait 1;
			continue;
		}

		carrier = candidates[ randomInt( candidates.size ) ];
		foreach ( player in level.players )
			if ( player != carrier )
				player iPrintLnBold( carrier.name + " has the bomb!" );
		carrier iPrintLnBold( "You have the bomb! Get a kill within " + level.funPotato + "s or explode" );
		timer = newClientHudElem( carrier );
		timer.alignX = "center";
		timer.horzAlign = "center";
		timer.y = 80;
		timer.fontScale = 2;
		timer.color = ( 1, 0.35, 0.25 );
		timer.archived = false;
		timer setTimer( level.funPotato );

		kills = carrier.pers[ "kills" ];
		start = getTime();
		while ( getTime() - start < level.funPotato * 1000 && isDefined( carrier ) && isAlive( carrier )
			&& carrier.pers[ "kills" ] == kills )
			wait 0.1;
		if ( isDefined( timer ) )
			timer destroy();

		last = undefined;
		if ( isDefined( carrier ) && isAlive( carrier ) )
		{
			if ( carrier.pers[ "kills" ] != kills )
			{
				carrier iPrintLnBold( "Bomb passed on!" );
				last = carrier;
				continue;
			}
			magicBullet( "ac130_105mm_mp", carrier.origin + ( 0, 0, 50 ), carrier.origin, carrier );
			wait 0.1;
			if ( isDefined( carrier ) && isAlive( carrier ) )
				carrier suicide();
			foreach ( player in level.players )
				player iPrintLnBold( carrier.name + " exploded!" );
		}
		wait 2;
	}
}

// air support per kill: every level.funAirKill kills add a random air killstreak to the stack
airPerKill()
{
	self endon( "disconnect" );
	self endon( "death" );

	kills = self.pers[ "kills" ];
	for ( ;; )
	{
		wait 0.1;
		if ( self.pers[ "kills" ] - kills < level.funAirKill )
			continue;
		kills = self.pers[ "kills" ];
		i = randomInt( level.airStreaks.size );
		// not earned: doesn't count toward the player's own streak, same as a care package
		self maps\mp\killstreaks\_killstreaks::giveKillstreak( level.airStreaks[ i ], false, false, self );
		self iPrintLnBold( "Air support: " + level.airNames[ i ] + "! Use it with the killstreak key" );
	}
}

// AC-130 lottery win: the cannon on top of the loadout, in hand right away
giveLotteryCannon()
{
	self giveWeapon( "ac130_105mm_mp" );
	self giveMaxAmmo( "ac130_105mm_mp" );
	self switchToWeapon( "ac130_105mm_mp" );
	self iPrintLnBold( "You won the AC-130 cannon!" );
}

// AC-130 rotation: one holder at a time; the cannon moves on after level.funRotate seconds,
// or right away when the holder dies or leaves, and every new holder gets the full time
rotateCannon()
{
	level endon( "game_ended" );

	for ( ;; )
	{
		holder = level.cannonHolder;
		candidates = [];
		foreach ( player in level.players )
			if ( isAlive( player ) && ( !isDefined( holder ) || player != holder ) )
				candidates[ candidates.size ] = player;
		// nobody else alive: the same player may keep it
		if ( !candidates.size && isDefined( holder ) && isAlive( holder ) )
			candidates[ 0 ] = holder;
		if ( !candidates.size )
		{
			wait 1;
			continue;
		}

		level.cannonHolder = candidates[ randomInt( candidates.size ) ];
		level.cannonHolder giveLotteryCannon();
		// big, centered, for everyone (the killfeed line was easy to miss)
		foreach ( player in level.players )
			if ( player != level.cannonHolder )
				player iPrintLnBold( level.cannonHolder.name + " has the AC-130 cannon!" );

		// a player who leaves becomes undefined, one who dies stops being alive
		start = getTime();
		while ( getTime() - start < level.funRotate * 1000 && isDefined( level.cannonHolder ) && isAlive( level.cannonHolder ) )
			wait 0.25;

		holder = level.cannonHolder;
		if ( isDefined( holder ) && isAlive( holder ) && holder hasWeapon( "ac130_105mm_mp" ) )
		{
			inHand = holder getCurrentWeapon() == "ac130_105mm_mp";
			holder takeWeapon( "ac130_105mm_mp" );
			primaries = holder getWeaponsListPrimaries();
			if ( inHand && primaries.size )
				holder switchToWeapon( primaries[ 0 ] );
			holder iPrintLnBold( "Time's up, the AC-130 cannon moves on" );
		}
	}
}

// the weapon in hand stays full, magazine included (no reloading), as long as the player lives
refillAmmo()
{
	self endon( "disconnect" );
	self endon( "death" );

	for ( ;; )
	{
		wait 0.2;
		weapon = self getCurrentWeapon();
		// the knife-only USP stays without bullets
		if ( weapon != "none" && weapon != "usp_tactical_mp" )
		{
			self giveMaxAmmo( weapon );
			self setWeaponAmmoClip( weapon, weaponClipSize( weapon ) );
		}
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
