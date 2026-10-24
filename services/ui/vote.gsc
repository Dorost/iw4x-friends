// In-game map vote and next game type, with chat commands and an on-screen list.
// Works with stock IW4x clients: chat comes in through IW4x's OnPlayerSay, keys through the
// use button (F), which every player has bound.
//
// Everyone can use all of it; every change is announced with the player's name, last one wins.
// Voting:   !1 .. !5 vote for a map (or press F to step through the options), !next, !help
// Picks:    !gt <mode> sets the next game type (tdm, ffa, dom, sd, hq, ...)
//           !gt alone opens a list on screen: F steps to the next mode, it closes by itself
//           !vote starts a map vote now (also mid-match), !cancel stops it
//           !map <name> sets the next map (short or partial names: rust, afghan, ship): no vote
//           after the match, that map loads; !map <name> now switches right away;
//           !map alone opens the map list (F = next, closes by itself); !map clear drops the pick
//           !menu opens a menu on screen (also: hold F for 1 s in the waiting room). Controls
//           frozen while it is open: aim (right mouse) up, fire (left mouse) down, F select,
//           melee (V) back / close. Closes after 20 s without input, on death and at match end.
// Lists:    ! alone (or !?) shows the commands on screen for 6 s; an unknown command shows the
//           ones that match it, an unknown or unclear !map / !gt name the maps or modes that do
// sv_vote_enabled 1: a match that ends by itself is followed by a map vote in the waiting room
//   (sv_hangout_enabled, lobby.gsc). The winner starts with the picked game type, or the
//   game type of the match that just ended.
// The web UI writes the installed maps and modes to userraw/scriptdata/vote.txt.
init()
{
	if ( getDvar( "sv_vote_enabled" ) == "" )
		setDvar( "sv_vote_enabled", 1 );
	level.voteActive = false;
	loadLists();
	OnPlayerSay( ::onSay );
	level thread start();
	level thread menuHoldWatch();
}

start()
{
	wait 0.05;  // lobby.gsc clears a stale sv_hangout first
	if ( !getDvarInt( "sv_hangout" ) )
	{
		// a real match: remembered for the vote that follows it
		setDvar( "sv_vote_prevmap", getDvar( "mapname" ) );
		setDvar( "sv_vote_prevmode", getDvar( "g_gametype" ) );
		setDvar( "sv_vote_pending", 0 );
		level waittill( "spawning_intermission" );  // ended by itself (score or time limit)
		if ( ( getDvarInt( "sv_vote_enabled" ) || pickedMap() != "" ) && getDvar( "sv_hangout_enabled" ) != "0" )
			setDvar( "sv_vote_pending", 1 );
		return;
	}

	if ( !getDvarInt( "sv_vote_pending" ) )
		return;
	setDvar( "sv_vote_pending", 0 );
	if ( pickedMap() != "" )
	{
		// someone picked the next map: no vote
		wait 4;
		map = pickedMap();
		if ( map == "" )
			return;
		iPrintLnBold( "Next: " + mapName( map ) + " - " + modeName( nextMode() ) );
		wait 3;
		startMatch( map, nextMode() );
		return;
	}
	// give everyone time to load into the waiting room
	wait 8;
	while ( !humans().size )
		wait 1;
	level thread runVote();
}

// ---------- map and mode lists ----------

loadLists()
{
	level.voteMaps = [];
	level.voteMapNames = [];
	level.voteModes = [];
	level.voteModeNames = [];
	text = "";
	if ( FileExists( "vote.txt" ) )
		text = FileRead( "vote.txt" );
	// lines: map<TAB>mp_rust<TAB>Rust, mode<TAB>war<TAB>Team Deathmatch
	foreach ( line in strTok( text, "\n" ) )
	{
		parts = strTok( line, "\t" );
		if ( parts.size < 3 )
			continue;
		if ( parts[ 0 ] == "map" )
		{
			level.voteMapNames[ level.voteMaps.size ] = parts[ 2 ];
			level.voteMaps[ level.voteMaps.size ] = parts[ 1 ];
		}
		else if ( parts[ 0 ] == "mode" )
		{
			level.voteModeNames[ level.voteModes.size ] = parts[ 2 ];
			level.voteModes[ level.voteModes.size ] = parts[ 1 ];
		}
	}
	if ( !level.voteMaps.size )
	{
		level.voteMaps = strTok( "mp_afghan mp_boneyard mp_brecourt mp_checkpoint mp_derail mp_estate mp_favela mp_highrise mp_invasion mp_nightshift mp_quarry mp_rundown mp_rust mp_subbase mp_terminal mp_underpass", " " );
		level.voteMapNames = level.voteMaps;
	}
	if ( !level.voteModes.size )
	{
		level.voteModes = strTok( "war dm dom sd koth sab ctf dd", " " );
		level.voteModeNames = level.voteModes;
	}
}

mapName( map )
{
	for ( i = 0; i < level.voteMaps.size; i++ )
		if ( level.voteMaps[ i ] == map )
			return level.voteMapNames[ i ];
	return map;
}

modeIndex( mode )
{
	for ( i = 0; i < level.voteModes.size; i++ )
		if ( level.voteModes[ i ] == mode )
			return i;
	return -1;
}

modeName( mode )
{
	i = modeIndex( mode );
	if ( i < 0 )
		return mode;
	return level.voteModeNames[ i ];
}

// the mode the next voted map starts with
nextMode()
{
	mode = getDvar( "sv_vote_mode" );
	if ( modeIndex( mode ) >= 0 )
		return mode;
	mode = getDvar( "sv_vote_prevmode" );
	if ( modeIndex( mode ) >= 0 )
		return mode;
	return getDvar( "g_gametype" );
}

// the playlist names players type (tdm, ffa, hq) -> script ids (war, dm, koth)
modeAlias( mode )
{
	switch ( mode )
	{
	case "tdm": return "war";
	case "ffa": return "dm";
	case "hq": return "koth";
	case "demo": return "dd";
	case "snd": return "sd";
	}
	return mode;
}

// ---------- chat ----------

// runs inside the chat message: no waits here. Returning 0 keeps the message out of the chat.
onSay( text, mode )
{
	if ( !isDefined( text ) || !text.size || text[ 0 ] != "!" )
		return 1;
	// IW4x can run the callback twice for one message (it is registered on every map load)
	key = getTime() + text;
	if ( isDefined( self.voteLastSay ) && self.voteLastSay == key )
		return 0;
	self.voteLastSay = key;
	self sayListClose();  // the next command hides a list

	args = strTok( toLowerAscii( getSubStr( text, 1, text.size ) ), " " );
	if ( !args.size || args[ 0 ] == "?" )
	{
		self commandList( "", "CHAT COMMANDS" );
		return 0;
	}
	cmd = args[ 0 ];

	if ( cmd == "v" && args.size > 1 )
		cmd = args[ 1 ];
	num = int( cmd );
	if ( num >= 1 && num <= 9 && cmd == "" + num )
	{
		if ( !level.voteActive )
			self iPrintLn( "No map vote running" );
		else if ( num > level.voteOptions.size )
			self iPrintLn( "Vote 1 to " + level.voteOptions.size );
		else
			self castVote( num - 1 );
		return 0;
	}

	switch ( cmd )
	{
	case "help":
		self iPrintLn( "!1 .. !5 or F: vote for a map   !next: next map and game type" );
		self iPrintLn( "!gt <mode> or !gt (list)   !vote   !cancel" );
		self iPrintLn( "!map <name> [now]   !map (list)   !map clear" );
		self iPrintLn( "!menu (or hold F in the waiting room): RMB up, LMB down, F select, V back" );
		return 0;
	case "next":
		next = "map vote";
		if ( pickedMap() != "" )
			next = mapName( pickedMap() );
		self iPrintLn( "Next: " + next + " - " + modeName( nextMode() ) );
		return 0;
	case "menu":
		if ( isDefined( self.menuOpen ) && self.menuOpen )
			self.menuStop = true;
		else
			self thread hudMenu();
		return 0;
	case "map":
		self mapCommand( args );
		return 0;
	case "gt":
	case "gametype":
	case "mode":
		if ( args.size < 2 )
		{
			if ( isDefined( self.voteMenuOpen ) && self.voteMenuOpen )
				self.voteMenuStop = true;
			else
				self thread modeMenu();
			return 0;
		}
		pick = modeAlias( args[ 1 ] );
		if ( modeIndex( pick ) < 0 )
		{
			list = "";
			foreach ( m in level.voteModes )
				list += m + " ";
			self iPrintLn( "Unknown game type. Pick one of: " + list );
			self modeList( args[ 1 ] );
			return 0;
		}
		self setNextMode( pick );
		return 0;
	case "vote":
	case "mapvote":
		self startVote();
		return 0;
	case "cancel":
		self cancelVote();
		return 0;
	}
	if ( !isSubStr( "abcdefghijklmnopqrstuvwxyz", cmd[ 0 ] ) )
		return 1;  // not one of ours ("!!!"): show it
	self iPrintLn( "Unknown command: !" + cmd );
	self commandList( cmd, "DID YOU MEAN" );
	return 0;
}

// ---------- suggestion lists (! alone, unknown names) ----------

// the chat commands with a name containing q ("" = all of them), as a list on screen
commandList( q, title )
{
	all = [];
	all[ all.size ] = "1 2 3 4 5|!1 .. !5|vote for a map (or F)";
	all[ all.size ] = "next|!next|next map and game type";
	all[ all.size ] = "gt gametype mode|!gt <mode>|next game type";
	all[ all.size ] = "gt gametype mode|!gt|game type list";
	all[ all.size ] = "map|!map <name>|next map";
	all[ all.size ] = "map|!map <name> now|switch map now";
	all[ all.size ] = "map|!map|map list";
	all[ all.size ] = "map|!map clear|drop the map pick";
	all[ all.size ] = "vote mapvote|!vote|start a map vote";
	all[ all.size ] = "cancel|!cancel|stop the map vote";
	all[ all.size ] = "menu|!menu|menu (or hold F)";
	all[ all.size ] = "help|!help|commands in chat";
	left = [];
	right = [];
	foreach ( c in all )
	{
		parts = strTok( c, "|" );
		hit = ( q == "" );
		foreach ( name in strTok( parts[ 0 ], " " ) )
			if ( isSubStr( name, q ) )
				hit = true;
		if ( hit )
		{
			left[ left.size ] = parts[ 1 ];
			right[ right.size ] = parts[ 2 ];
		}
	}
	if ( !left.size )
	{
		self commandList( "", "CHAT COMMANDS" );
		return;
	}
	self thread sayList( title, left, right );
}

// game types whose id or name contains q, else all of them
modeList( q )
{
	title = "DID YOU MEAN";
	left = [];
	right = [];
	for ( pass = 0; pass < 2; pass++ )
	{
		left = [];
		right = [];
		for ( i = 0; i < level.voteModes.size; i++ )
		{
			if ( pass == 0 && !isSubStr( toLowerAscii( level.voteModes[ i ] ), q )
				&& !isSubStr( toLowerAscii( level.voteModeNames[ i ] ), q ) )
				continue;
			left[ left.size ] = "!gt " + level.voteModes[ i ];
			right[ right.size ] = level.voteModeNames[ i ];
		}
		if ( left.size )
			break;
		title = "GAME TYPES";
	}
	self thread sayList( title, left, right );
}

// a list on screen for this player only, gone after 6 s or with the next command
sayList( title, left, right )
{
	self sayListClose();  // a new list replaces the old one
	self endon( "disconnect" );
	self endon( "say_list" );

	n = left.size;
	more = ( n > 15 );
	if ( more )
		n = 14;
	lines = n;
	if ( more )
		lines++;
	x = -150;
	top = -20 - lines * 8;
	elems = [];
	bg = newClientHudElem( self );
	bg.horzAlign = "center";
	bg.vertAlign = "middle";
	bg.alignX = "left";
	bg.alignY = "top";
	bg.x = x - 8;
	bg.y = top - 12;
	bg.color = ( 0, 0, 0 );
	bg.alpha = 0.6;
	bg.sort = -2;
	bg.hideWhenInMenu = true;
	bg.archived = false;
	bg setShader( "white", 316, lines * 16 + 48 );
	elems[ elems.size ] = bg;
	head = self hudMenuText( x, top, 1.5, "objective" );
	head setText( title );
	head.color = ( 0.55, 0.85, 1 );
	elems[ elems.size ] = head;
	for ( i = 0; i < n; i++ )
	{
		row = self hudMenuText( x, top + 26 + i * 16, 1.2, "default" );
		row setText( left[ i ] );
		elems[ elems.size ] = row;
		if ( !isDefined( right ) )
			continue;
		desc = self hudMenuText( x + 130, top + 26 + i * 16, 1.2, "default" );
		desc setText( right[ i ] );
		desc.color = ( 0.7, 0.7, 0.7 );
		elems[ elems.size ] = desc;
	}
	if ( more )
	{
		row = self hudMenuText( x, top + 26 + n * 16, 1.2, "default" );
		row setText( "... type more letters" );
		row.color = ( 0.7, 0.7, 0.7 );
		elems[ elems.size ] = row;
	}
	self.sayListHud = elems;
	wait 6;
	self sayListDestroy();
}

sayListClose()
{
	self notify( "say_list" );
	self sayListDestroy();
}

sayListDestroy()
{
	if ( !isDefined( self.sayListHud ) )
		return;
	foreach ( e in self.sayListHud )
		if ( isDefined( e ) )
			e destroy();
	self.sayListHud = undefined;
}

// ---------- actions, announced to everyone (self = the player) ----------

whoName()
{
	if ( isDefined( self ) && isPlayer( self ) )
		return plainName( self.name );
	return "Server";
}

startVote()
{
	if ( level.voteActive )
	{
		self iPrintLn( "A map vote is already running" );
		return;
	}
	iPrintLn( self whoName() + " started a map vote" );
	level thread runVote();
}

cancelVote()
{
	if ( !level.voteActive )
	{
		self iPrintLn( "No map vote running" );
		return;
	}
	level.voteCancelled = true;
	iPrintLn( self whoName() + " cancelled the map vote" );
}

clearMapPick()
{
	setDvar( "sv_vote_map", "none" );
	iPrintLn( self whoName() + " cleared the map pick: next map by vote" );
}

switchTo( map )
{
	level.voteCancelled = true;  // a running vote stops without switching
	iPrintLn( self whoName() + " switched the map to " + mapName( map ) );
	level thread switchNow( map );
}

setNextMode( mode )
{
	setDvar( "sv_vote_mode", mode );
	iPrintLn( self whoName() + " set next game type: " + modeName( mode ) );
	if ( level.voteActive && isDefined( level.voteModeHud ) )
		level.voteModeHud setText( modeName( mode ) );
}

toLowerAscii( s )
{
	upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
	lower = "abcdefghijklmnopqrstuvwxyz";
	out = "";
	for ( i = 0; i < s.size; i++ )
	{
		c = s[ i ];
		for ( j = 0; j < 26; j++ )
		{
			if ( c == upper[ j ] )
			{
				c = lower[ j ];
				break;
			}
		}
		out += c;
	}
	return out;
}

// ---------- players ----------

humans()
{
	list = [];
	foreach ( player in level.players )
		if ( !player isTestClient() )
			list[ list.size ] = player;
	return list;
}


plainName( name )
{
	out = "";
	for ( i = 0; i < name.size; i++ )
	{
		if ( name[ i ] == "^" && i + 1 < name.size )
		{
			i++;  // skip the color code
			continue;
		}
		out += name[ i ];
	}
	return out;
}


// ---------- game type list (!gt) ----------

modeMenu()
{
	self endon( "disconnect" );

	self.voteMenuOpen = true;
	self.voteMenuStop = false;
	sel = modeIndex( nextMode() );
	if ( sel < 0 )
		sel = 0;
	startSel = sel;  // nothing picked unless F is pressed

	elems = [];
	title = self menuText( -20 - level.voteModes.size * 14 / 2, 1.4, "objective" );
	title setText( "NEXT GAME TYPE   (F = next)" );
	elems[ elems.size ] = title;
	top = title.y + 22;
	for ( i = 0; i < level.voteModes.size; i++ )
	{
		row = self menuText( top + i * 14, 1.2, "default" );
		row setText( level.voteModeNames[ i ] );
		elems[ elems.size ] = row;
	}
	bar = newClientHudElem( self );
	bar.horzAlign = "left";
	bar.vertAlign = "middle";
	bar.alignX = "left";
	bar.alignY = "middle";
	bar.x = 8;
	bar.alpha = 0.35;
	bar.color = ( 0.3, 0.6, 1 );
	bar.hideWhenInMenu = true;
	bar.archived = false;
	bar.sort = -1;
	bar setShader( "white", 180, 13 );
	elems[ elems.size ] = bar;

	idle = 0;
	for ( ;; )
	{
		bar.y = top + sel * 14;
		if ( self.voteMenuStop || idle >= 120 )  // 6 s without a press
			break;
		if ( self useButtonPressed() )
		{
			sel = ( sel + 1 ) % level.voteModes.size;
			idle = 0;
			while ( self useButtonPressed() )
				wait 0.05;
			continue;
		}
		idle++;
		wait 0.05;
	}
	if ( sel != startSel && level.voteModes[ sel ] != getDvar( "sv_vote_mode" ) )
		self setNextMode( level.voteModes[ sel ] );
	foreach ( e in elems )
		e destroy();
	self.voteMenuOpen = false;
}

menuText( y, scale, font )
{
	t = newClientHudElem( self );
	t.horzAlign = "left";
	t.vertAlign = "middle";
	t.alignX = "left";
	t.alignY = "middle";
	t.x = 12;
	t.y = y;
	t.font = font;
	t.fontScale = scale;
	t.hideWhenInMenu = true;
	t.archived = false;
	return t;
}

// ---------- map vote ----------

runVote()
{
	if ( level.voteActive )
		return;
	level.voteActive = true;
	level endon( "game_ended" );

	// up to 4 random maps, not the one just played or this one
	pool = [];
	foreach ( map in level.voteMaps )
		if ( map != getDvar( "mapname" ) && map != getDvar( "sv_vote_prevmap" ) )
			pool[ pool.size ] = map;
	if ( !pool.size )
		pool = level.voteMaps;
	level.voteOptions = [];
	while ( level.voteOptions.size < 4 && pool.size )
	{
		i = randomInt( pool.size );
		level.voteOptions[ level.voteOptions.size ] = pool[ i ];
		pool[ i ] = pool[ pool.size - 1 ];
		pool[ pool.size - 1 ] = undefined;
	}

	foreach ( player in level.players )
		player.voteChoice = -1;

	seconds = 20;
	hud = [];
	top = -70;
	title = voteText( top, 1.5, "objective" );
	title setText( "VOTE FOR THE NEXT MAP" );
	title.color = ( 0.55, 0.85, 1 );
	hud[ hud.size ] = title;
	level.voteModeHud = voteText( top + 18, 1.2, "default" );
	level.voteModeHud setText( modeName( nextMode() ) );
	level.voteModeHud.color = ( 0.8, 0.8, 0.8 );
	hud[ hud.size ] = level.voteModeHud;
	counts = [];
	for ( i = 0; i < level.voteOptions.size; i++ )
	{
		row = voteText( top + 40 + i * 16, 1.3, "default" );
		row setText( "!" + ( i + 1 ) + "  " + mapName( level.voteOptions[ i ] ) );
		hud[ hud.size ] = row;
		c = voteText( top + 40 + i * 16, 1.3, "default" );
		c.x = 170;
		c setValue( 0 );
		hud[ hud.size ] = c;
		counts[ i ] = c;
	}
	hint = voteText( top + 46 + level.voteOptions.size * 16, 1.1, "default" );
	hint setText( "F or !1-!" + level.voteOptions.size + " in chat to vote" );
	hint.color = ( 0.75, 0.75, 0.75 );
	hud[ hud.size ] = hint;
	timer = voteText( top, 1.5, "objective" );
	timer.x = 170;
	timer setTimer( seconds );
	hud[ hud.size ] = timer;

	foreach ( player in humans() )
		player thread voteKeys();
	level thread voteJoiners();

	level.voteCancelled = false;
	for ( t = 0; t < seconds * 4 && !level.voteCancelled; t++ )
	{
		tally = voteTally();
		for ( i = 0; i < counts.size; i++ )
			counts[ i ] setValue( tally[ i ] );
		wait 0.25;
	}
	level notify( "vote_done" );

	tally = voteTally();
	foreach ( e in hud )
		e destroy();
	foreach ( player in level.players )
		if ( isDefined( player.voteBar ) )
			player.voteBar destroy();
	level.voteModeHud = undefined;
	level.voteActive = false;
	if ( level.voteCancelled )
		return;

	// most votes wins, a tie (or no votes) is a coin flip among the best
	best = 0;
	foreach ( n in tally )
		if ( n > best )
			best = n;
	winners = [];
	for ( i = 0; i < tally.size; i++ )
		if ( tally[ i ] == best )
			winners[ winners.size ] = i;
	map = level.voteOptions[ winners[ randomInt( winners.size ) ] ];
	mode = nextMode();
	iPrintLnBold( "Next: " + mapName( map ) + " - " + modeName( mode ) );
	wait 3;
	startMatch( map, mode );
}

voteTally()
{
	tally = [];
	for ( i = 0; i < level.voteOptions.size; i++ )
		tally[ i ] = 0;
	foreach ( player in humans() )
		if ( isDefined( player.voteChoice ) && player.voteChoice >= 0 && player.voteChoice < tally.size )
			tally[ player.voteChoice ]++;
	return tally;
}

voteText( y, scale, font )
{
	t = newHudElem();
	t.horzAlign = "left";
	t.vertAlign = "middle";
	t.alignX = "left";
	t.alignY = "middle";
	t.x = 12;
	t.y = y;
	t.font = font;
	t.fontScale = scale;
	t.hideWhenInMenu = true;
	t.archived = false;
	return t;
}

voteJoiners()
{
	level endon( "vote_done" );
	level endon( "game_ended" );

	for ( ;; )
	{
		level waittill( "connected", player );
		player.voteChoice = -1;
		if ( !player isTestClient() )
			player thread voteKeys();
	}
}

// F steps through the options; the highlighted one is your vote
voteKeys()
{
	self endon( "disconnect" );
	level endon( "vote_done" );
	level endon( "game_ended" );

	for ( ;; )
	{
		if ( self useButtonPressed() && !( isDefined( self.menuOpen ) && self.menuOpen ) )
		{
			if ( !isDefined( self.voteChoice ) )
				self.voteChoice = -1;
			self castVote( ( self.voteChoice + 1 ) % level.voteOptions.size );
			while ( self useButtonPressed() )
				wait 0.05;
		}
		wait 0.05;
	}
}

castVote( choice )
{
	self.voteChoice = choice;
	if ( !isDefined( self.voteBar ) )
	{
		bar = newClientHudElem( self );
		bar.horzAlign = "left";
		bar.vertAlign = "middle";
		bar.alignX = "left";
		bar.alignY = "middle";
		bar.x = 8;
		bar.alpha = 0.35;
		bar.color = ( 0.3, 0.6, 1 );
		bar.hideWhenInMenu = true;
		bar.archived = false;
		bar.sort = -1;
		bar setShader( "white", 180, 15 );
		self.voteBar = bar;
	}
	self.voteBar.y = -70 + 40 + choice * 16;
}

// same as the web UI's Start game from a running match: settings from server.cfg, then the map
startMatch( map, mode )
{
	cmds = [];
	if ( getDvarInt( "sv_hangout" ) )
	{
		// the waiting room set these to 0 (no limits): back to the mode's defaults
		cmds[ cmds.size ] = "reset scr_dm_timelimit";
		cmds[ cmds.size ] = "reset scr_dm_scorelimit";
	}
	cmds[ cmds.size ] = "set sv_hangout 0";
	cmds[ cmds.size ] = "exec server.cfg";
	cmds[ cmds.size ] = "set sv_vote_mode none";  // the picks are used up
	cmds[ cmds.size ] = "set sv_vote_map none";
	cmds[ cmds.size ] = "g_gametype " + mode;
	cmds[ cmds.size ] = "ui_gametype " + mode;
	cmds[ cmds.size ] = "ui_mapname " + map;
	cmds[ cmds.size ] = "map " + map;
	foreach ( cmd in cmds )
		Exec( cmd );
}

// ---------- map pick (!map) ----------

// the picked next map, "" when there is none
pickedMap()
{
	map = getDvar( "sv_vote_map" );
	for ( i = 0; i < level.voteMaps.size; i++ )
		if ( level.voteMaps[ i ] == map )
			return map;
	return "";
}

setNextMap( map )
{
	setDvar( "sv_vote_map", map );
	iPrintLn( self whoName() + " set next map: " + mapName( map ) + " - " + modeName( nextMode() ) );
}

// !map, !map <name>, !map <name> now, !map clear (args[ 0 ] is "map")
mapCommand( args )
{
	if ( args.size < 2 )
	{
		if ( isDefined( self.voteMapMenuOpen ) && self.voteMapMenuOpen )
			self.voteMapMenuStop = true;
		else
			self thread mapMenu();
		return;
	}
	if ( args.size == 2 && ( args[ 1 ] == "clear" || args[ 1 ] == "vote" || args[ 1 ] == "none" ) )
	{
		self clearMapPick();
		return;
	}
	now = ( args[ args.size - 1 ] == "now" );
	last = args.size;
	if ( now )
		last--;
	query = "";
	for ( i = 1; i < last; i++ )
	{
		if ( query != "" )
			query += " ";
		query += args[ i ];
	}
	if ( query == "" )
	{
		self iPrintLn( "Usage: !map <name> [now]" );
		return;
	}
	maps = findMaps( query );
	if ( !maps.size )
	{
		self iPrintLn( "Unknown map: " + query + ". Try: " + mapSuggestions( query ) );
		self thread sayList( "DID YOU MEAN", mapSuggestionList( query ) );
		return;
	}
	if ( maps.size > 1 )
	{
		self iPrintLn( "More than one map matches " + query + ": type more letters" );
		names = [];
		foreach ( m in maps )
			names[ names.size ] = mapName( m );
		self thread sayList( "DID YOU MEAN", names );
		return;
	}
	map = maps[ 0 ];
	if ( !now )
	{
		self setNextMap( map );
		return;
	}
	self switchTo( map );
}

switchNow( map )
{
	mode = nextMode();
	iPrintLnBold( "Switching to " + mapName( map ) + " - " + modeName( mode ) );
	wait 2;
	startMatch( map, mode );
}

// exact id or name, then the start of one, then anywhere in it: the maps of the first of
// these that matches (one for an exact match), none when nothing matches
findMaps( query )
{
	q = toLowerAscii( query );
	found = [];
	for ( pass = 0; pass < 3; pass++ )
	{
		for ( i = 0; i < level.voteMaps.size; i++ )
		{
			id = toLowerAscii( level.voteMaps[ i ] );
			bare = id;
			if ( isSubStr( id, "mp_" ) && getSubStr( id, 0, 3 ) == "mp_" )
				bare = getSubStr( id, 3, id.size );
			name = toLowerAscii( level.voteMapNames[ i ] );
			if ( pass == 0 && ( q == id || q == bare || q == name ) )
			{
				found[ 0 ] = level.voteMaps[ i ];
				return found;
			}
			if ( pass == 1 && ( startsWith( bare, q ) || startsWith( name, q ) ) )
				found[ found.size ] = level.voteMaps[ i ];
			if ( pass == 2 && ( isSubStr( bare, q ) || isSubStr( name, q ) ) )
				found[ found.size ] = level.voteMaps[ i ];
		}
		if ( found.size )
			return found;
	}
	return found;
}

startsWith( s, prefix )
{
	return s.size >= prefix.size && getSubStr( s, 0, prefix.size ) == prefix;
}

// up to 5 map names sharing the first letter of the query, else the first 5
mapSuggestions( query )
{
	first = getSubStr( toLowerAscii( query ), 0, 1 );
	out = "";
	n = 0;
	for ( i = 0; i < level.voteMaps.size && n < 5; i++ )
	{
		if ( startsWith( toLowerAscii( level.voteMapNames[ i ] ), first ) )
		{
			if ( n )
				out += ", ";
			out += level.voteMapNames[ i ];
			n++;
		}
	}
	for ( i = 0; i < level.voteMaps.size && n < 5; i++ )
	{
		if ( !startsWith( toLowerAscii( level.voteMapNames[ i ] ), first ) )
		{
			if ( n )
				out += ", ";
			out += level.voteMapNames[ i ];
			n++;
		}
	}
	return out;
}

// map names sharing the first letter of the query, else all of them
mapSuggestionList( query )
{
	first = getSubStr( toLowerAscii( query ), 0, 1 );
	out = [];
	foreach ( name in level.voteMapNames )
		if ( startsWith( toLowerAscii( name ), first ) )
			out[ out.size ] = name;
	if ( !out.size )
		out = level.voteMapNames;
	return out;
}

// on-screen map list, 15 per page: F steps to the next map, closes after 6 s without a press
// and keeps the highlighted map as the next one
mapMenu()
{
	self endon( "disconnect" );

	self.voteMapMenuOpen = true;
	self.voteMapMenuStop = false;
	per = 15;
	sel = 0;
	for ( i = 0; i < level.voteMaps.size; i++ )
		if ( level.voteMaps[ i ] == pickedMap() )
			sel = i;
	startSel = sel;  // nothing picked unless F is pressed or a map was picked before

	elems = [];
	title = self menuText( -20 - per * 14 / 2, 1.4, "objective" );
	title setText( "NEXT MAP   (F = next)" );
	elems[ elems.size ] = title;
	pageHud = self menuText( title.y, 1.4, "objective" );
	pageHud.x = 190;
	elems[ elems.size ] = pageHud;
	top = title.y + 22;
	rows = [];
	for ( i = 0; i < per; i++ )
	{
		rows[ i ] = self menuText( top + i * 14, 1.2, "default" );
		elems[ elems.size ] = rows[ i ];
	}
	bar = newClientHudElem( self );
	bar.horzAlign = "left";
	bar.vertAlign = "middle";
	bar.alignX = "left";
	bar.alignY = "middle";
	bar.x = 8;
	bar.alpha = 0.35;
	bar.color = ( 0.3, 0.6, 1 );
	bar.hideWhenInMenu = true;
	bar.archived = false;
	bar.sort = -1;
	bar setShader( "white", 180, 13 );
	elems[ elems.size ] = bar;

	page = -1;
	idle = 0;
	for ( ;; )
	{
		if ( int( sel / per ) != page )
		{
			page = int( sel / per );
			for ( i = 0; i < per; i++ )
			{
				j = page * per + i;
				if ( j < level.voteMaps.size )
					rows[ i ] setText( level.voteMapNames[ j ] );
				else
					rows[ i ] setText( "" );
			}
			pageHud setValue( page + 1 );
		}
		bar.y = top + ( sel % per ) * 14;
		if ( self.voteMapMenuStop || idle >= 120 )
			break;
		if ( self useButtonPressed() )
		{
			sel = ( sel + 1 ) % level.voteMaps.size;
			idle = 0;
			while ( self useButtonPressed() )
				wait 0.05;
			continue;
		}
		idle++;
		wait 0.05;
	}
	if ( sel != startSel || pickedMap() != "" )
	{
		if ( level.voteMaps[ sel ] != pickedMap() )
			self setNextMap( level.voteMaps[ sel ] );
	}
	else
		self iPrintLn( "Map list closed, no map picked" );
	foreach ( e in elems )
		e destroy();
	self.voteMapMenuOpen = false;
}

// ---------- on-screen menu (!menu) ----------

// waiting room only (no objectives to hold F for): holding F for 1 s opens the menu
menuHoldWatch()
{
	level endon( "game_ended" );

	wait 0.05;
	if ( !getDvarInt( "sv_hangout" ) )
		return;
	for ( ;; )
	{
		foreach ( player in humans() )
		{
			if ( !isDefined( player.menuHold ) )
				player.menuHold = 0;
			busy = level.voteActive || ( isDefined( player.menuOpen ) && player.menuOpen )
				|| ( isDefined( player.voteMenuOpen ) && player.voteMenuOpen )
				|| ( isDefined( player.voteMapMenuOpen ) && player.voteMapMenuOpen );
			if ( !busy && player useButtonPressed() )
			{
				player.menuHold++;
				if ( player.menuHold == 20 )
					player thread hudMenu();
			}
			else if ( !player useButtonPressed() )
				player.menuHold = 0;
		}
		wait 0.05;
	}
}

hudMenu()
{
	self endon( "disconnect" );

	if ( isDefined( self.menuOpen ) && self.menuOpen )
		return;
	self.menuOpen = true;
	self.menuStop = false;
	self.voteMenuStop = true;     // the F-only lists of !gt and !map
	self.voteMapMenuStop = true;
	self freezeControls( true );
	self disableWeapons();

	per = 12;
	x = -150;
	top = -100;
	elems = [];
	bg = newClientHudElem( self );
	bg.horzAlign = "center";
	bg.vertAlign = "middle";
	bg.alignX = "left";
	bg.alignY = "top";
	bg.x = x - 8;
	bg.y = top - 12;
	bg.color = ( 0, 0, 0 );
	bg.alpha = 0.6;
	bg.sort = -2;
	bg.hideWhenInMenu = true;
	bg.archived = false;
	bg setShader( "white", 316, 72 + per * 16 + 30 );
	elems[ elems.size ] = bg;
	title = self hudMenuText( x, top, 1.5, "objective" );
	title setText( "SERVER MENU" );
	title.color = ( 0.55, 0.85, 1 );
	elems[ elems.size ] = title;
	crumb = self hudMenuText( x, top + 20, 1.1, "default" );
	crumb.color = ( 0.7, 0.7, 0.7 );
	elems[ elems.size ] = crumb;
	status = self hudMenuText( x, top + 36, 1.2, "default" );
	status.color = ( 1, 0.85, 0.4 );
	elems[ elems.size ] = status;
	rowsTop = top + 60;
	rows = [];
	for ( i = 0; i < per; i++ )
	{
		rows[ i ] = self hudMenuText( x + 14, rowsTop + i * 16, 1.3, "default" );
		elems[ elems.size ] = rows[ i ];
	}
	bar = newClientHudElem( self );
	bar.horzAlign = "center";
	bar.vertAlign = "middle";
	bar.alignX = "left";
	bar.alignY = "middle";
	bar.x = x - 4;
	bar.color = ( 0.3, 0.6, 1 );
	bar.alpha = 0.45;
	bar.sort = -1;
	bar.hideWhenInMenu = true;
	bar.archived = false;
	bar setShader( "white", 300, 15 );
	elems[ elems.size ] = bar;
	arrow = self hudMenuText( x, 0, 1.3, "default" );
	arrow setText( ">" );
	arrow.color = ( 1, 1, 1 );
	elems[ elems.size ] = arrow;
	footer = self hudMenuText( x, rowsTop + per * 16 + 6, 1.1, "default" );
	footer setText( "RMB up   LMB down   F select   V back" );
	footer.color = ( 0.7, 0.7, 0.7 );
	elems[ elems.size ] = footer;
	self thread hudMenuCleanup( elems );

	screen = "main";
	sel = 0;
	mapSel = 0;
	drawn = "";
	shownStatus = "";
	idle = 0;
	wasAlive = isAlive( self );
	// a button already held when the menu opens (F after holding it) does nothing until released
	prevUp = self adsButtonPressed();
	prevDown = self attackButtonPressed();
	prevUse = self useButtonPressed();
	prevBack = self meleeButtonPressed();
	holdUp = 0;
	holdDown = 0;

	for ( ;; )
	{
		items = hudMenuItems( screen, mapSel );
		if ( sel >= items.size )
			sel = items.size - 1;
		page = int( sel / per );
		key = screen + " " + page + " " + mapSel;
		if ( key != drawn )
		{
			drawn = key;
			for ( i = 0; i < per; i++ )
			{
				j = page * per + i;
				if ( j < items.size )
					rows[ i ] setText( items[ j ] );
				else
					rows[ i ] setText( "" );
			}
			crumb setText( hudMenuCrumb( screen, page, int( ( items.size + per - 1 ) / per ), mapSel ) );
		}
		next = "map vote";
		if ( pickedMap() != "" )
			next = mapName( pickedMap() );
		line = "Next: " + next + " - " + modeName( nextMode() );
		if ( level.voteActive )
			line = line + "   (vote running)";
		if ( line != shownStatus )
		{
			shownStatus = line;
			status setText( line );
		}
		bar.y = rowsTop + ( sel % per ) * 16 + 7;
		arrow.y = rowsTop + ( sel % per ) * 16;

		if ( self.menuStop || idle >= 400 || ( wasAlive && !isAlive( self ) )
			|| ( isDefined( level.gameEnded ) && level.gameEnded ) )
			break;

		up = self adsButtonPressed();
		down = self attackButtonPressed();
		pressUse = self useButtonPressed();
		pressBack = self meleeButtonPressed();
		if ( up || down || pressUse || pressBack )
			idle = 0;
		else
			idle++;

		// one step per press, then repeating while held
		if ( up )
			holdUp++;
		else
			holdUp = 0;
		if ( down )
			holdDown++;
		else
			holdDown = 0;
		if ( ( up && !prevUp ) || ( holdUp > 8 && holdUp % 3 == 0 ) )
			sel = ( sel + items.size - 1 ) % items.size;
		if ( ( down && !prevDown ) || ( holdDown > 8 && holdDown % 3 == 0 ) )
			sel = ( sel + 1 ) % items.size;

		if ( pressBack && !prevBack )
		{
			if ( screen == "main" )
				break;
			if ( screen == "mapaction" )
			{
				screen = "map";
				sel = mapSel;
			}
			else
			{
				screen = "main";
				sel = 0;
			}
		}
		else if ( pressUse && !prevUse )
		{
			result = self hudMenuSelect( screen, sel, mapSel );
			if ( result == "close" )
				break;
			if ( result == "map" && screen == "mapaction" )
			{
				screen = "map";  // Back from the map's actions
				sel = mapSel;
			}
			else if ( result == "map" )
			{
				screen = "map";
				sel = 0;
				for ( i = 0; i < level.voteMaps.size; i++ )
					if ( level.voteMaps[ i ] == pickedMap() )
						sel = i;
			}
			else if ( result == "mapaction" )
			{
				mapSel = sel;
				screen = "mapaction";
				sel = 0;
			}
			else if ( result == "mode" )
			{
				screen = "mode";
				sel = modeIndex( nextMode() );
				if ( sel < 0 )
					sel = 0;
			}
			else if ( result == "main" )
			{
				screen = "main";
				sel = 0;
			}
		}
		prevUp = up;
		prevDown = down;
		prevUse = pressUse;
		prevBack = pressBack;
		wait 0.05;
	}

	self notify( "menu_closed" );
	foreach ( e in elems )
		e destroy();
	self freezeControls( false );
	self enableWeapons();
	self.menuOpen = false;
}

hudMenuCleanup( elems )
{
	self endon( "menu_closed" );
	self waittill( "disconnect" );
	foreach ( e in elems )
		if ( isDefined( e ) )
			e destroy();
}

hudMenuText( x, y, scale, font )
{
	t = newClientHudElem( self );
	t.horzAlign = "center";
	t.vertAlign = "middle";
	t.alignX = "left";
	t.alignY = "top";
	t.x = x;
	t.y = y;
	t.font = font;
	t.fontScale = scale;
	t.hideWhenInMenu = true;
	t.archived = false;
	return t;
}

hudMenuItems( screen, mapSel )
{
	if ( screen == "mode" )
		return level.voteModeNames;
	if ( screen == "map" )
		return level.voteMapNames;
	if ( screen == "mapaction" )
		return strTok( "Next match,Switch now,Back", "," );
	return strTok( "Game type,Map,Start map vote,Cancel map vote,Clear map pick,Close", "," );
}

hudMenuCrumb( screen, page, pages, mapSel )
{
	if ( screen == "mode" )
		return "Main > Game type";
	if ( screen == "map" )
		return "Main > Map   page " + ( page + 1 ) + "/" + pages;
	if ( screen == "mapaction" )
		return "Main > Map > " + level.voteMapNames[ mapSel ];
	return "Main";
}

// what F does on a row: the screen to show next, "close", or "" to stay
hudMenuSelect( screen, sel, mapSel )
{
	if ( screen == "mode" )
	{
		self setNextMode( level.voteModes[ sel ] );
		return "main";
	}
	if ( screen == "map" )
		return "mapaction";
	if ( screen == "mapaction" )
	{
		if ( sel == 0 )
		{
			self setNextMap( level.voteMaps[ mapSel ] );
			return "main";
		}
		if ( sel == 1 )
		{
			self switchTo( level.voteMaps[ mapSel ] );
			return "close";
		}
		return "map";
	}
	switch ( sel )
	{
	case 0:
		return "mode";
	case 1:
		return "map";
	case 2:
		self startVote();
		return "close";
	case 3:
		self cancelVote();
		return "";
	case 4:
		self clearMapPick();
		return "";
	}
	return "close";
}
