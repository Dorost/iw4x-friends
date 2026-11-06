// What the bots say in chat: the lines of userraw/scriptdata/botchat.txt (services/ui/botchat.txt,
// how it works is in the notes at its top). Replaces Bot Warfare's own chat (the bot mod in
// userraw/z_svr_bots.iwd, maps/mp/bots/_bot_chat.gsc), whose English lines that file started
// from: this turns that off (bots_main_chat 0) and talks at the same moments, with the same
// waits and chances. Those moments come from Bot Warfare (bot_connected, bot_event) and the
// game (killed_enemy, death, game_ended, a nuke). Bot Warfare's radio messages ("Follow me!",
// "Enemy spotted!", with their sound) aren't chat lines and stay as they are.
init()
{
	setDvar( "bots_main_chat", 0 );
	level.botChat = [];
	text = "";
	if ( FileExists( "botchat.txt" ) )
		text = FileRead( "botchat.txt" );
	section = undefined;
	foreach ( line in strTok( text, "\r\n" ) )
	{
		if ( line[ 0 ] == "#" || !strTok( line, " \t" ).size )
			continue;
		if ( line[ 0 ] == "[" )
			section = newSection( line );
		else if ( isDefined( section ) )
			section.lines[ section.lines.size ] = line;
	}
	if ( !level.botChat.size )
		return;
	// the map's name as the web UI's map list has it (vote.txt), else its id
	level.botChatMap = getDvar( "mapname" );
	if ( FileExists( "vote.txt" ) )
	{
		foreach ( line in strTok( FileRead( "vote.txt" ), "\n" ) )
		{
			parts = strTok( line, "\t" );
			if ( parts.size >= 3 && parts[ 0 ] == "map" && parts[ 1 ] == getDvar( "mapname" ) )
				level.botChatMap = parts[ 2 ];
		}
	}
	level thread botsJoining();
}

// "[kill] 5%": the section's name and its chance (10% without one)
newSection( line )
{
	close = indexOf( line, "]", 1 );
	if ( close < 0 )
		close = line.size;
	s = spawnStruct();
	s.lines = [];
	s.chance = 10;
	if ( close + 1 < line.size )
	{
		rest = strTok( getSubStr( line, close + 1, line.size ), " \t%" );
		if ( rest.size )
			s.chance = int( rest[ 0 ] );
	}
	level.botChat[ getSubStr( line, 1, close ) ] = s;
	return s;
}

botsJoining()
{
	for ( ;; )
	{
		level waittill( "bot_connected", bot );
		bot thread botChat();
	}
}

botChat()
{
	self.botChatStreak = 0;
	self thread onStart();
	self thread onKill();
	self thread onDeath();
	self thread onNuke();
	self thread onEnd();
	self thread onBotEvent();
}

// ---------- the moments ----------

onStart()
{
	self endon( "disconnect" );
	wait 0.05 + randomInt( 5 ) + randomInt( 5 );
	self say( "start " + level.gameType );
	wait 2;
	for ( i = 0; i < 3; i++ )
	{
		if ( self getPlayerData( "killstreaks", i ) == "nuke" )
		{
			self say( "start nuke" );
			return;
		}
	}
}

onKill()
{
	self endon( "disconnect" );
	for ( ;; )
	{
		self waittill( "killed_enemy" );
		streak = self.pers[ "cur_kill_streak" ];
		for ( i = self.botChatStreak + 1; i <= streak; i++ )
			self thread sayStreak( i );
		self.botChatStreak = streak;
		self thread sayKill( self.lastKilledPlayer );
	}
}

sayStreak( streak )
{
	self endon( "disconnect" );
	if ( !isDefined( level.botChat[ "streak " + streak ] ) )
		return;
	tags = [];
	if ( isDefined( self.pers[ "lastEarnedStreak" ] ) && self.pers[ "lastEarnedStreak" ] == "nuke" )
		tags[ 0 ] = "nuke";
	else if ( getDvarInt( "bots_loadout_allow_op" ) )
		tags[ 0 ] = "no nuke";
	else
		tags[ 0 ] = "nukes off";
	self say( "streak " + streak, undefined, tags );
}

sayKill( victim )
{
	self endon( "disconnect" );
	if ( !isDefined( victim ) || !isDefined( victim.name ) )
		return;
	v = [];
	v[ "name" ] = victim.name;
	v[ "map" ] = level.botChatMap;
	v[ "mystreak" ] = self.pers[ "cur_kill_streak" ];
	if ( isDefined( victim.pers ) )
		v[ "theirdeaths" ] = victim.pers[ "cur_death_streak" ];
	if ( isDefined( victim.attackerData ) && isDefined( victim.attackerData[ self.guid ] ) )
		v[ "weapon" ] = baseWeapon( victim.attackerData[ self.guid ].weapon );
	wait randomInt( 3 ) + 1;
	self say( "kill", v );
}

onDeath()
{
	self endon( "disconnect" );
	for ( ;; )
	{
		self waittill( "death" );
		lost = self.botChatStreak;
		self.botChatStreak = 0;
		self thread sayDeath( self.lastAttacker, lost );
	}
}

sayDeath( killer, lost )
{
	self endon( "disconnect" );
	if ( !isDefined( killer ) || !isDefined( killer.name ) )
		return;
	v = [];
	v[ "name" ] = killer.name;
	v[ "map" ] = level.botChatMap;
	v[ "mystreak" ] = lost;
	v[ "mydeaths" ] = self.pers[ "cur_death_streak" ];
	v[ "random" ] = level.players[ randomInt( level.players.size ) ].name;
	if ( isDefined( killer.pers ) )
		v[ "theirstreak" ] = killer.pers[ "cur_kill_streak" ];
	if ( isDefined( self.attackerData ) && isDefined( killer.guid ) && isDefined( self.attackerData[ killer.guid ] ) )
		v[ "weapon" ] = baseWeapon( self.attackerData[ killer.guid ].weapon );
	tags = [];
	if ( lost > 0 )
		tags[ 0 ] = "streak";
	else
		tags[ 0 ] = "no streak";
	wait randomInt( 3 ) + 1;
	self say( "death", v, tags );
}

// someone's nuke is coming (as Bot Warfare: looks every few seconds, once per nuke)
onNuke()
{
	self endon( "disconnect" );
	for ( ;; )
	{
		while ( !isDefined( level.nukeIncoming ) && !isDefined( level.moabIncoming ) )
			wait 0.05 + randomInt( 4 );
		self thread sayNuke();
		timer = 10;
		if ( isDefined( level.nukeTimer ) )
			timer = level.nukeTimer;
		wait timer + 5;
	}
}

sayNuke()
{
	info = level.nukeInfo;
	if ( !isDefined( info ) || !isDefined( info.player ) )
		return;
	v = [];
	v[ "name" ] = info.player.name;
	tags = [];
	if ( info.player == self )
		tags[ tags.size ] = "mine";
	else
		tags[ tags.size ] = "theirs";
	if ( isDefined( info.team ) && isDefined( self.team ) )
	{
		if ( info.team == self.team )
			tags[ tags.size ] = "my team";
		else
			tags[ tags.size ] = "their team";
	}
	self say( "nuke", v, tags );
}

onEnd()
{
	self endon( "disconnect" );
	level waittill( "game_ended" );
	wait 0.05 + randomInt( 6 ) + randomInt( 6 );
	winner = undefined;
	loser = undefined;
	foreach ( player in level.players )
	{
		if ( !isDefined( winner ) || player.pers[ "score" ] > winner.pers[ "score" ] )
			winner = player;
		if ( !isDefined( loser ) || player.pers[ "score" ] < loser.pers[ "score" ] )
			loser = player;
	}
	v = [];
	v[ "winner" ] = winner.name;
	v[ "loser" ] = loser.name;
	v[ "team" ] = self.pers[ "team" ];
	tags = [];
	if ( self == winner )
		tags[ 0 ] = "best";
	else if ( self == loser )
		tags[ 0 ] = "worst";
	else
		tags[ 0 ] = "other";
	key = "end ffa";
	if ( level.teamBased )
	{
		winningTeam = maps\mp\gametypes\_gamescore::getWinningTeam();
		if ( self.pers[ "team" ] == winningTeam )
			key = "end won";
		else if ( winningTeam != "none" )
			key = "end lost";
		else
			key = "end draw";
	}
	self say( key, v, tags );
}

// what Bot Warfare reports the bot doing: [<event> <state>], game modes [<mode> <what> <state>]
onBotEvent()
{
	self endon( "disconnect" );
	level endon( "game_ended" );
	for ( ;; )
	{
		self waittill( "bot_event", msg, a, b, c );
		self thread botEvent( msg, a, b, c );
	}
}

botEvent( msg, a, b, c )
{
	self endon( "disconnect" );
	key = msg;
	switch ( msg )
	{
		case "killstreak":  // ("call", name of the killstreak) or ("camp", name, spot)
			if ( isDefined( a ) && a == "call" && isDefined( b ) )
				key = "killstreak " + b;
			else if ( isDefined( a ) )
				key = "killstreak " + a;
			break;
		case "chat":  // ("chat", message, who): only people, or bots would answer each other forever
			if ( !isDefined( c ) || isDefined( c.pers[ "isBot" ] ) )
				return;
			break;
		case "dom":
		case "hq":
		case "sab":
		case "sd":
		case "cap":
		case "dem":
		case "gtnw":
		case "oneflag":
		case "arena":
		case "vip":  // (go/start/stop, what)
			if ( !isDefined( a ) || !isDefined( b ) )
				return;
			key = msg + " " + b + " " + a;
			break;
		default:
			if ( isDefined( a ) )
				key = msg + " " + a;
	}
	if ( !isDefined( level.botChat[ key ] ) )
		return;

	v = [];
	tags = [];
	switch ( msg )
	{
		case "revive":
		case "heard_target":
			if ( isDefined( b ) )
				v[ "name" ] = b.name;
			break;
		case "follow":
			if ( !isDefined( b ) )
				return;
			v[ "name" ] = b.name;
			v[ "seconds" ] = c;
			break;
		case "camp":
			v[ "seconds" ] = c;
			break;
		case "equ":
		case "nade":
			v[ "weapon" ] = baseWeapon( c );
			break;
		case "attack_vehicle":  // (state, the killstreak, launcher if it uses one)
			if ( !isDefined( c ) )
				c = self getCurrentWeapon();
			v[ "weapon" ] = baseWeapon( c );
			break;
		case "crate_cap":  // (state, the crate, who took it)
			if ( !isDefined( b ) )
				return;
			v[ "crate" ] = b.crateType;
			if ( a == "captured" )
			{
				if ( isDefined( c ) )
					v[ "name" ] = c.name;
			}
			else if ( !isDefined( b.owner ) || b.owner == self )
				tags[ 0 ] = "mine";
			else
			{
				tags[ 0 ] = "theirs";
				v[ "name" ] = b.owner.name;
			}
			break;
		case "connection":  // (connected/disconnected, player, name)
			v[ "name" ] = c;
			break;
		case "chat":
			v[ "name" ] = c.name;
			break;
	}
	self say( key, v, tags );
}

// ---------- saying a line ----------

// With the section's chance, the bot says one of its lines, picked at random from the ones that
// can be said now: v has the {...} values of the moment, tags the (...) that apply.
say( key, v, tags )
{
	s = level.botChat[ key ];
	if ( !isDefined( s ) || randomInt( 100 ) >= s.chance )
		return;
	if ( !isDefined( v ) )
		v = [];
	if ( !isDefined( tags ) )
		tags = [];
	// try the lines in random order until one works
	order = [];
	for ( i = 0; i < s.lines.size; i++ )
		order[ i ] = i;
	for ( left = order.size; left > 0; left-- )
	{
		r = randomInt( left );
		text = fillLine( s.lines[ order[ r ] ], v, tags );
		if ( isDefined( text ) )
		{
			self sayAll( text );
			return;
		}
		order[ r ] = order[ left - 1 ];
	}
}

// the line with its {...} filled in, undefined when it can't be said now
fillLine( line, v, tags )
{
	i = 0;
	if ( line[ 0 ] == "(" )
	{
		close = indexOf( line, ")", 1 );
		if ( close < 0 || !listHas( tags, getSubStr( line, 1, close ) ) )
			return undefined;
		i = close + 1;
		if ( i < line.size && line[ i ] == " " )
			i++;
	}
	out = "";
	while ( i < line.size )
	{
		open = indexOf( line, "{", i );
		close = -1;
		if ( open >= 0 )
			close = indexOf( line, "}", open + 1 );
		if ( close < 0 )
			return out + getSubStr( line, i, line.size );
		out += getSubStr( line, i, open );
		name = getSubStr( line, open + 1, close );
		if ( name == "color" )
			out += "^" + ( randomInt( 6 ) + 1 );
		else if ( name == "wasd" )
			out += wasd();
		else if ( isDefined( v[ name ] ) )
			out += v[ name ];
		else
			return undefined;
		i = close + 1;
	}
	return out;
}

// what a bot types when it's stuck (as Bot Warfare)
wasd()
{
	keys = "wsdaWSDA ";
	out = "";
	for ( n = randomIntRange( 5, 30 ); n > 0; n-- )
		out += keys[ randomInt( keys.size ) ];
	return out;
}

// "cheytac_fmj_mp" -> "cheytac"
baseWeapon( weapon )
{
	if ( !isDefined( weapon ) )
		return undefined;
	parts = strTok( weapon, "_" );
	return parts[ 0 ];
}

indexOf( s, c, from )
{
	for ( i = from; i < s.size; i++ )
	{
		if ( s[ i ] == c )
			return i;
	}
	return -1;
}

listHas( list, item )
{
	foreach ( x in list )
	{
		if ( x == item )
			return true;
	}
	return false;
}
