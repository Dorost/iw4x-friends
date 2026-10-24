// In-game map vote and next game type, with chat commands and an on-screen list.
// Works with stock IW4x clients: chat comes in through IW4x's OnPlayerSay, keys through the
// use button (F), which every player has bound.
//
// Anyone:   !1 .. !5 vote for a map (or press F to step through the options), !next, !help
// Admins:   !gt <mode> sets the next game type (tdm, ffa, dom, sd, hq, ...)
//           !gt alone opens a list on screen: F steps to the next mode, it closes by itself
//           !vote starts a map vote now (also mid-match), !cancel stops it
//           !map <name> sets the next map (short or partial names: rust, afghan, ship): no vote
//           after the match, that map loads; !map <name> now switches right away;
//           !map alone opens the map list (F = next, closes by itself); !map clear drops the pick
// sv_vote_admins: names or GUIDs, comma separated (web UI). Empty: the human player with the
//   lowest client number (usually the first to join) is the admin.
// sv_vote_enabled 1: a match that ends by itself is followed by a map vote in the waiting room
//   (sv_hangout_enabled, lobby.gsc). The winner starts with the admin's game type, or the
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
		// the admin picked the next map: no vote
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
	if ( !isDefined( text ) || text.size < 2 || text[ 0 ] != "!" )
		return 1;
	// IW4x can run the callback twice for one message (it is registered on every map load)
	key = getTime() + text;
	if ( isDefined( self.voteLastSay ) && self.voteLastSay == key )
		return 0;
	self.voteLastSay = key;

	args = strTok( toLowerAscii( getSubStr( text, 1, text.size ) ), " " );
	if ( !args.size )
		return 1;
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
		if ( self isAdmin() )
		{
			self iPrintLn( "Admin: !gt <mode> or !gt (list)   !vote   !cancel" );
			self iPrintLn( "Admin: !map <name> [now]   !map (list)   !map clear" );
		}
		return 0;
	case "next":
		next = "map vote";
		if ( pickedMap() != "" )
			next = mapName( pickedMap() );
		self iPrintLn( "Next: " + next + " - " + modeName( nextMode() ) );
		return 0;
	case "map":
		if ( !self isAdmin() )
		{
			self iPrintLn( "Only an admin can pick the map" );
			return 0;
		}
		self mapCommand( args );
		return 0;
	case "gt":
	case "gametype":
	case "mode":
		if ( !self isAdmin() )
		{
			self iPrintLn( "Only an admin can pick the game type" );
			return 0;
		}
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
			return 0;
		}
		setNextMode( pick );
		return 0;
	case "vote":
	case "mapvote":
		if ( !self isAdmin() )
			self iPrintLn( "Only an admin can start a map vote" );
		else if ( level.voteActive )
			self iPrintLn( "A map vote is already running" );
		else
			level thread runVote();
		return 0;
	case "cancel":
		if ( self isAdmin() && level.voteActive )
		{
			level.voteCancelled = true;
			iPrintLn( "Map vote cancelled" );
		}
		return 0;
	}
	return 1;  // not one of ours: show it
}

setNextMode( mode )
{
	setDvar( "sv_vote_mode", mode );
	iPrintLn( "Next game type: " + modeName( mode ) );
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

// ---------- admins ----------

humans()
{
	list = [];
	foreach ( player in level.players )
		if ( !player isTestClient() )
			list[ list.size ] = player;
	return list;
}

isAdmin()
{
	entries = strTok( getDvar( "sv_vote_admins" ), "," );
	if ( !entries.size )
	{
		// nobody configured: the human with the lowest client number
		first = undefined;
		foreach ( player in humans() )
			if ( !isDefined( first ) || player getEntityNumber() < first getEntityNumber() )
				first = player;
		return isDefined( first ) && first == self;
	}
	name = ToUpper( plainName( self.name ) );
	guid = ToUpper( self getGuid() );
	foreach ( entry in entries )
	{
		e = ToUpper( trim( entry ) );
		if ( e != "" && ( e == name || e == guid ) )
			return true;
	}
	return false;
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

trim( s )
{
	start = 0;
	end = s.size;
	while ( start < end && s[ start ] == " " )
		start++;
	while ( end > start && s[ end - 1 ] == " " )
		end--;
	return getSubStr( s, start, end );
}

// ---------- admin game type list ----------

modeMenu()
{
	self endon( "disconnect" );

	self.voteMenuOpen = true;
	self.voteMenuStop = false;
	sel = modeIndex( nextMode() );
	if ( sel < 0 )
		sel = 0;

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
	if ( level.voteModes[ sel ] != getDvar( "sv_vote_mode" ) )
		setNextMode( level.voteModes[ sel ] );
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
		if ( self useButtonPressed() )
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
	cmds[ cmds.size ] = "set sv_vote_mode none";  // the admin's picks are used up
	cmds[ cmds.size ] = "set sv_vote_map none";
	cmds[ cmds.size ] = "g_gametype " + mode;
	cmds[ cmds.size ] = "ui_gametype " + mode;
	cmds[ cmds.size ] = "ui_mapname " + map;
	cmds[ cmds.size ] = "map " + map;
	foreach ( cmd in cmds )
		Exec( cmd );
}

// ---------- admin map pick ----------

// the admin's next map, "" when there is none
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
	iPrintLn( "Next map: " + mapName( map ) + " - " + modeName( nextMode() ) );
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
		setDvar( "sv_vote_map", "none" );
		iPrintLn( "Next map: map vote" );
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
	map = findMap( query );
	if ( map == "" )
	{
		self iPrintLn( "Unknown map: " + query + ". Try: " + mapSuggestions( query ) );
		return;
	}
	if ( !now )
	{
		setNextMap( map );
		return;
	}
	level.voteCancelled = true;  // a running vote stops without switching
	level thread switchNow( map );
}

switchNow( map )
{
	mode = nextMode();
	iPrintLnBold( "Switching to " + mapName( map ) + " - " + modeName( mode ) );
	wait 2;
	startMatch( map, mode );
}

// exact id or name, then the start of one, then anywhere in it; "" when nothing matches
findMap( query )
{
	q = toLowerAscii( query );
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
				return level.voteMaps[ i ];
			if ( pass == 1 && ( startsWith( bare, q ) || startsWith( name, q ) ) )
				return level.voteMaps[ i ];
			if ( pass == 2 && ( isSubStr( bare, q ) || isSubStr( name, q ) ) )
				return level.voteMaps[ i ];
		}
	}
	return "";
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
			setNextMap( level.voteMaps[ sel ] );
	}
	else
		self iPrintLn( "Map list closed, no map picked" );
	foreach ( e in elems )
		e destroy();
	self.voteMapMenuOpen = false;
}
