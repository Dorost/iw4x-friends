// Weapon modes from the web UI's Fun panel (read when a match starts). Off in the waiting
// room (sv_hangout), which has no weapons at all.
// sv_funweapons: after every spawn the class loadout is swapped for a weapon of the mode,
// picked at random per spawn.
//   0 classes, 1 knife only, 2 snipers, 3 pistols, 4 shotguns, 5 launchers (ammo refills),
//   6 riot shields, 7 roulette (any weapon), 8 akimbo, 9 one in the chamber (Deagle with
//   one bullet, one more per kill), 10 AC-130 cannons (ammo refills)
// sv_funammo 1: the weapon in hand never runs out of ammo, no reloading.
// sv_funlottery N: every spawn has a 1 in N chance to come with an extra AC-130 cannon.
// sv_funrotate N: every N seconds the AC-130 cannon moves to another random living player.
init()
{
	if ( getDvarInt( "sv_hangout" ) )
		return;

	level.funWeaponMode = getDvarInt( "sv_funweapons" );
	level.funAmmo = getDvarInt( "sv_funammo" );
	level.funLottery = getDvarInt( "sv_funlottery" );
	level.funRotate = getDvarInt( "sv_funrotate" );
	if ( !level.funWeaponMode && !level.funAmmo && !level.funLottery && !level.funRotate )
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
	default: list = snipers + " " + pistols + " " + shotguns + " " + rifles + " " + smgs + " " + lmgs + " rpg_mp riotshield_mp"; break;
	}
	level.funWeapons = strTok( list, " " );
	level thread onConnect();
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
		// no endless ammo for modes that live off having none
		if ( level.funAmmo && level.funWeaponMode != 1 && level.funWeaponMode != 9 )
			self thread refillAmmo();
	}
}

giveFunWeapon()
{
	weapon = level.funWeapons[ randomInt( level.funWeapons.size ) ];
	self takeAllWeapons();
	self giveWeapon( weapon, 0, level.funWeaponMode == 8 );
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
		self thread refillAmmo();
		break;
	case 9:
		self setWeaponAmmoClip( weapon, 1 );
		self setWeaponAmmoStock( weapon, 0 );
		self thread bulletPerKill( weapon );
		break;
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

// AC-130 rotation: one holder at a time, the cannon moves on every level.funRotate seconds
rotateCannon()
{
	level endon( "game_ended" );

	for ( ;; )
	{
		wait level.funRotate;
		holder = level.cannonHolder;
		if ( isDefined( holder ) && isAlive( holder ) && holder hasWeapon( "ac130_105mm_mp" ) )
		{
			inHand = holder getCurrentWeapon() == "ac130_105mm_mp";
			holder takeWeapon( "ac130_105mm_mp" );
			primaries = holder getWeaponsListPrimaries();
			if ( inHand && primaries.size )
				holder switchToWeapon( primaries[ 0 ] );
		}

		candidates = [];
		foreach ( player in level.players )
			if ( isAlive( player ) && ( !isDefined( holder ) || player != holder ) )
				candidates[ candidates.size ] = player;
		if ( !candidates.size )
			continue;

		level.cannonHolder = candidates[ randomInt( candidates.size ) ];
		level.cannonHolder giveLotteryCannon();
		iPrintLn( level.cannonHolder.name + " has the AC-130 cannon" );
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
		if ( weapon != "none" )
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
