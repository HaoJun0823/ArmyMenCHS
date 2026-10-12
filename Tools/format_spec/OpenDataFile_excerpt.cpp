	int mapsize = sizeof(the_map);

	//initialize the count of animated objects
	the_map.num_animated_objects=0;

	if (_LOAD_FROM_DATAFILE)
		OpenDataFile( the_map.terrain_name );

	// load sprites for objects we have into sprite arrays in each category
	for( i = 0; i < the_map.num_objects; i++ )	
	{
		category = the_map.objects[i].category;

		MissionLoading( (long)(1300 + i * (float)(2000.0/(float)the_map.num_objects)), 20000 );
		if( _LOAD_FROM_DATAFILE )
		{
			the_map.objects[i].cell.pSprite = AcquireObjectSprite( category, the_map.objects[i].number, 0 );
			if( the_map.objects[i].cell.pSprite )
			{
				hotspot = the_map.objects[i].cell.pSprite->hotspot;
				linkspot = the_map.objects[i].cell.pSprite->linkspot;
			}
		}
		else
		{										// load all damage levels now
			index = the_map.objects[i].index;
			pObjSprite = the_map.obj_sprite_array_list[category];

			if (pObjSprite)	
			{
 				if (!pObjSprite[index].sprites)	
 				{
//					TRACE( "%14s   %4d\n", obj_category_dirs[category], the_map.objects[i].number );
					LoadObjectSprites(i,&pObjSprite[index], the_map.objects[i].number, category, obj_dir, &objsize);
					count++;
					total_objsize.number += objsize.number;
					total_objsize.data_size += objsize.data_size;
					total_objsize.graphics_size += objsize.graphics_size;
					total_objsize.base_graphics_size += objsize.base_graphics_size;
					total_objsize.mask_size += objsize.mask_size;
				}

	 			if (pObjSprite[index].sprites)	
				{
					if (the_map.objects[i].triggers & TRIGGER_DESTROYED)
					{
						the_map.objects[i].cell.pSprite=&pObjSprite[index].sprites[pObjSprite[index].nLevelsOfDamage-1];
						the_map.objects[i].damageindex=pObjSprite[index].nLevelsOfDamage-1;
					}
					else
						the_map.objects[i].cell.pSprite=&pObjSprite[index].sprites[0];

					hotspot = pObjSprite[index].sprites[0].hotspot;
					linkspot = pObjSprite[index].sprites[0].linkspot;		

					//if this object is animated
					if (pObjSprite[index].nAnimFrames>0)
					{
						ANIMATED_OBJECT *pAnimObject;

						if (the_map.num_animated_objects==MAX_NUM_ANIMATED_OBJECTS)
							TRACE("ERROR: too many animated objects\n");

						pAnimObject=&the_map.animatedobjects[the_map.num_animated_objects++];

						pAnimObject->pObj=&the_map.objects[i];
						pAnimObject->curframe=(rand() % pObjSprite[index].nAnimFrames);
						if (pObjSprite[index].nAnimDelay)
							pAnimObject->curcounter=(rand() % pObjSprite[index].nAnimDelay);
						else
							pAnimObject->curcounter=0;
					}
				}
				else	
				{
					TRACE("ERROR: no graphic for object %d/%d\n", category, the_map.objects[i].number);
						the_map.objects[i].cell.flags = ANIM_FLAG_CELL;
				}

			}
			else
				TRACE("ERROR: no obj_sprite_array_list for category %d", category);
		}

		the_map.objects[i].cell.flags = ANIM_FLAG_CELL;
		AnimCellSetOwner( &the_map.objects[i].cell, &the_map.objects[i] );

		if( the_map.objects[i].cell.pSprite )
		{				
			//	set cell flags
			the_map.objects[i].cell.flags |= ANIM_FLAG_ACTIVE;
			if( the_map.objects[i].triggers & TRIGGER_INVISIBLE )
				the_map.objects[i].cell.flags |= ANIM_FLAG_INVISIBLE;
			if( the_map.objects[i].triggers & TRIGGER_UNDEPLOYED )
				the_map.objects[i].cell.flags &= ~ANIM_FLAG_ACTIVE;


			the_map.objects[i].cell.world_pos.x += hotspot.x-linkspot.x;
			the_map.objects[i].cell.world_pos.y += hotspot.y-linkspot.y;
			the_map.objects[i].common.tile = IPOINT_FROM_SPOINT( the_map.objects[i].cell.world_pos );

			the_map.objects[i].cell.order = i + 1;
