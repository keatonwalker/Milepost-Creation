"""Functions to create 1/4 mile rail road mile posts."""
import arcpy
import os
import shutil

WORKING_DIRECTORY = r'C:\GisWork\RailRoad_mp\testing'
WORKING_GDB = 'Milepost_result_features.gdb'


def renew_working_directory(directory=WORKING_DIRECTORY):
    if os.path.exists(directory):
        shutil.rmtree(directory)
        print 'Working directory removed'

    os.makedirs(directory)
    arcpy.CreateFileGDB_management(directory, WORKING_GDB)


def combine_line_features(lines, points, id_field, output_workspace):

    dissolved_lines = arcpy.Dissolve_management(in_features=lines,
                                                out_feature_class=os.path.join(output_workspace, 'dissolved_lines'),
                                                dissolve_field=id_field,
                                                multi_part="SINGLE_PART",
                                                unsplit_lines="UNSPLIT_LINES")[0]
    freq_table = arcpy.Frequency_analysis(dissolved_lines,
                                          os.path.join(output_workspace, 'dissolve_freq'),
                                          id_field)[0]
    id_counts = {}
    with arcpy.da.SearchCursor(freq_table, ['FREQUENCY', id_field]) as cursor:
        for count, id_value in cursor:
            id_counts[id_value] = count

    separate_ids = [x for x in id_counts if id_counts[x] > 1]
    separate_where = "{} IN ('{}')".format(id_field, "','".join(separate_ids))
    # import pdb; pdb.set_trace()
    separate_layer = arcpy.MakeFeatureLayer_management(dissolved_lines, 'separate_lines', separate_where)[0].name
    arcpy.CopyFeatures_management(separate_layer, os.path.join(output_workspace, 'separate_id_lines'))
    arcpy.DeleteFeatures_management(separate_layer)

    points_where = "{} NOT IN ('{}')".format(id_field, "','".join(separate_ids))
    points_for_lines_layer = arcpy.MakeFeatureLayer_management(points, 'relevant_points', points_where)[0].name
    points_for_dissolve_lines = arcpy.CopyFeatures_management(points_for_lines_layer,
                                                              os.path.join(output_workspace,
                                                                           'relevant_points_for_lines'))[0]

    return (dissolved_lines, points_for_dissolve_lines)


def _sub_divide(current_dist, next_dist, line, main_spacing=None, allowed_error=None, number_of_divisions=None):

    def _match_number(next_dist, current_dist, divisions):
        n = divisions
        space = next_dist - current_dist
        new_point_spacing = space / n
        new_point_count = n - 1

        return (new_point_spacing, new_point_count)

    def _match_spacing(next_dist, current_dist):
        n = 2
        space = next_dist - current_dist
        next_div = space / n
        cur_div = space
        while abs(next_div - main_spacing) < abs(cur_div - main_spacing):
            cur_div = next_div
            n += 1
            next_div = space / n

        new_point_spacing = cur_div
        new_point_count = n - 2

        return (new_point_spacing, new_point_count)

    subdivide_points = []
    if allowed_error is None:
        allowed_error = 1
    # if next_dist - current_dist < main_spacing * allowed_error:
    #     import pdb; pdb.set_trace()
    #     print 'error'
    #     raise(Exception('small dist error'))

    # print '{} to {}:'.format(current_dist, next_dist), next_dist - current_dist
    new_point_spacing, new_point_count = (None, None)
    if main_spacing is not None:
        new_point_spacing, new_point_count = _match_spacing(next_dist, current_dist)
    elif number_of_divisions is not None:
        new_point_spacing, new_point_count = _match_number(next_dist, current_dist, number_of_divisions)
    for i in range(new_point_count):
        # print '\tNew point at:', current_dist + new_point_spacing * (i + 1)
        new_point_dist = current_dist + new_point_spacing * (i + 1)
        subdivide_points.append((line.positionAlongLine(new_point_dist), new_point_dist))
    return subdivide_points


def get_id_lines_and_milepost_distances(mileposts, milepost_id, lines, line_id):
    """Create tuples of (milepost geometry, distance on line)."""
    line_divsion_geomtries = None
    with arcpy.da.SearchCursor(lines, [line_id, 'SHAPE@']) as cursor:
        line_divsion_geomtries = dict(cursor)

    distance_mps = dict(((d, []) for d in line_divsion_geomtries.keys()))
    with arcpy.da.SearchCursor(mileposts, [milepost_id, 'SHAPE@']) as cursor:
        for div, shape in cursor:
            rail_distance = line_divsion_geomtries[div].measureOnLine(shape)
            distance_mps[div].append((shape, rail_distance))

    return (distance_mps, line_divsion_geomtries)


def add_distance_to_mp(distance_mps, line_divsion_geomtries, main_spacing, allowed_error, number_of_divisions=None):
    def _add_new_subdivision_points(distance_mps, division, current_dist, next_dist, div_line, main_spacing, allowed_error):
        new_point_dists = _sub_divide(current_dist, next_dist, div_line, main_spacing, allowed_error)
        # new_point_dists = [(point, dist, division) for point, dist in new_point_dists]
        distance_mps[division].extend(new_point_dists)

    def _add_new_number_points(distance_mps, division, current_dist, next_dist, div_line, number_of_divisions):
        new_point_dists = _sub_divide(current_dist, next_dist, div_line, number_of_divisions=number_of_divisions)
        # new_point_dists = [(point, dist, division) for point, dist in new_point_dists]
        distance_mps[division].extend(new_point_dists)

    new_distance_mps = {}
    for div in distance_mps:
        print div
        div_line = line_divsion_geomtries[div]
        new_distance_mps[div] = []
        mps = sorted(distance_mps[div], key=lambda mp: mp[1])
        if len(mps) == 0:  # Add start and end point if no milepost exist
            start_end = [(div_line.positionAlongLine(0, use_percentage=True), 0),
                         (div_line.positionAlongLine(1, use_percentage=True), div_line.length)]
            mps.extend(start_end)
            # new_distance_mps[div].extend(start_end)
        mp_last_i = len(mps) - 1
        mps = list(enumerate(mps))
        for i, mp in mps:
            new_distance_mps[div].append(mp)
            if i == mp_last_i:  # last point
                mp_shape = mp[0]
                last_to_end_dist = mp_shape.distanceTo(div_line.lastPoint)
                if last_to_end_dist > main_spacing * allowed_error:
                    current_dist = mp[1]
                    next_dist = last_to_end_dist + current_dist
                    _add_new_subdivision_points(new_distance_mps,
                                                div,
                                                current_dist,
                                                next_dist,
                                                div_line,
                                                main_spacing,
                                                allowed_error)
                    new_last_point = div_line.positionAlongLine(1, use_percentage=True)
                    new_distance_mps[div].append((new_last_point, next_dist))
                    print 'add end'
                    # add end point as new
                break
            elif i == 0:  # first point
                mp_shape = mp[0]
                first_to_start_dist = mp_shape.distanceTo(div_line.firstPoint)
                if first_to_start_dist > main_spacing * allowed_error:
                    print 'add start'
                    current_dist = 0
                    next_dist = mp[1]
                    _add_new_subdivision_points(new_distance_mps,
                                                div,
                                                current_dist,
                                                next_dist,
                                                div_line,
                                                main_spacing,
                                                allowed_error)
                    new_first_point = div_line.positionAlongLine(0, use_percentage=True)
                    new_distance_mps[div].append((new_first_point, current_dist))
            # All other points
            current_dist = mp[1]
            next_dist = mps[i + 1][1][1]
            if number_of_divisions is not None:
                _add_new_number_points(new_distance_mps,
                                       div,
                                       current_dist,
                                       next_dist,
                                       div_line,
                                       number_of_divisions)
            else:
                _add_new_subdivision_points(new_distance_mps,
                                            div,
                                            current_dist,
                                            next_dist,
                                            div_line,
                                            main_spacing,
                                            allowed_error)

        print
    return new_distance_mps


def create_output_feature(output_gdb, name, id_field, spatial_ref):
    output = arcpy.CreateFeatureclass_management(output_gdb, name, 'POINT', spatial_reference=spatial_ref)[0]
    arcpy.AddField_management(output, 'line_distance', 'DOUBLE')
    arcpy.AddField_management(output, id_field, 'TEXT')
    arcpy.AddField_management(output, 'point_number', 'DOUBLE')

    return output


def update_quarters():
    quarters = r'C:\GisWork\RailRoad_mp\Utah_Railroads.gdb\New_QuarterMps'

    with arcpy.da.UpdateCursor(quarters, ['line_distance', 'RR_Milepos_1', 'RR_Milepos_Q', 'DIVISION'], sql_clause=(None, 'ORDER BY DIVISION, line_distance')) as cursor:
        main_mp = 0
        q_mp_fraction = 0.25
        for row in cursor:
            main_number = row[1]
            if main_number != -1: # TODO reset main_map when id changes
                main_mp = main_number
                q_mp_fraction = 0.25
                continue

            row[2] = main_mp + q_mp_fraction
            q_mp_fraction += 0.25
            cursor.updateRow(row)



if __name__ == '__main__':
    update_quarters()
    # renew_working_directory()
    # error = 0.25
    # main_spacing = 1609.34
    # allowed_error_distance_factor = 1 - error
    #
    # output_gdb = os.path.join(WORKING_DIRECTORY, WORKING_GDB)
    #
    # mp_features = r'C:\GisWork\RailRoad_mp\Utah_Railroads.gdb\Mileposts_of_concern'
    # mp_divsion_field = 'DIVISION'
    # lines = r'C:\GisWork\RailRoad_mp\Utah_Railroads.gdb\Railroads_for_mp'
    # rail_division_field = 'DIVISION'
    #
    # disovled_lines, relevant_points = combine_line_features(lines, mp_features, rail_division_field, output_gdb)
    # # rail_features = r'C:\GisWork\RailRoad_mp\Utah_Railroads.gdb\Railroad_divisions'
    # print 'mileposts'
    # mile_mps, line_divsion_geomtries = get_id_lines_and_milepost_distances(relevant_points,
    #                                                                        mp_divsion_field,
    #                                                                        disovled_lines,
    #                                                                        rail_division_field)
    #
    # new_main_mps = add_distance_to_mp(mile_mps, line_divsion_geomtries, main_spacing, allowed_error_distance_factor)
    #
    # # for line_id in mile_mps:
    # #     mile_mps[line_id].extend(new_main_mps[line_id])
    # print 'quarter mps'
    # quarter_spacing = main_spacing / 4
    # quarter_mps = add_distance_to_mp(new_main_mps, line_divsion_geomtries, quarter_spacing, allowed_error_distance_factor, number_of_divisions=4)
    #
    # print 'copying'
    # output_miles = create_output_feature(output_gdb, 'miles', mp_divsion_field, arcpy.SpatialReference(26912))
    # with arcpy.da.InsertCursor(output_miles, ['SHAPE@', 'line_distance', mp_divsion_field, 'point_number']) as cursor:
    #     for shared_id in new_main_mps:
    #         count = 0
    #         new_main_mps[shared_id].sort(key=lambda p: p[1])
    #         for point in new_main_mps[shared_id]:
    #             cursor.insertRow(point + (shared_id, count))
    #             count += 1
    #
    # new_mile_points = []
    # for points in new_main_mps.values():
    #     new_mile_points.extend([p[0] for p in points])
    # arcpy.CopyFeatures_management(new_mile_points, os.path.join(output_gdb, 'new_miles'))
    #
    # output_quarters = create_output_feature(output_gdb, 'quarters', mp_divsion_field, arcpy.SpatialReference(26912))
    # with arcpy.da.InsertCursor(output_quarters, ['SHAPE@', 'line_distance', mp_divsion_field, 'point_number']) as cursor:
    #     for shared_id in quarter_mps:
    #         count = 0
    #         quarter_mps[shared_id].sort(key=lambda p: p[1])
    #         for point in quarter_mps[shared_id]:
    #             cursor.insertRow(point + (shared_id, count))
    #             count += 1
    # new_quarter_points = []
    # for points in quarter_mps.values():
    #     new_quarter_points.extend([p[0] for p in points])
    # arcpy.CopyFeatures_management(new_quarter_points, os.path.join(output_gdb, 'new_quarters'))
