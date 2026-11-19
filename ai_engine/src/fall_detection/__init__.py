def candidate(features, motion, raw_posture, config):
    if not features or not motion.prior_upright:
        return False
    rapid_drop=motion.hip_drop>=config.fall_hip_drop and motion.hip_down_speed>=config.fall_hip_speed
    rotation=(raw_posture in ('LYING','COLLAPSED_TORSO') and motion.angle_delta>=config.fall_angle_delta
              and motion.angle_speed>=config.fall_angle_speed)
    # A forward collapse can shorten its 2D projection without a horizontal torso.
    # Require visible full limbs, large height collapse, angle change and rapid hip descent.
    projection=(raw_posture=='COLLAPSED_BODY' and features.coverage=='FULL'
                and motion.height_ratio<=config.fall_height_ratio
                and motion.angle_delta>=config.fall_foreshortening_angle_delta)
    return bool(rapid_drop and (rotation or projection))
