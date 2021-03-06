#
# face_track.py -  Registery and tracking of faces
# Copyright (C) 2014,2015  Hanson Robotics
# Copyright (C) 2015 Linas Vepstas
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

import time

from owyl import blackboard
import rospy
from pi_face_tracker.msg import FaceEvent, Faces
from blender_api_msgs.msg import Target

# A Face. Currently consists only of an ID number, a 3D location,
# and the time it was last seen.  Should be extended to include
# the size of the face, possibly the location of the eyes, and,
# if possible, the name of the human attached to it ...
class Face:
	def __init__(self, fid, point):
		self.faceid = fid
		self.x = point.x
		self.y = point.y
		self.z = point.z
		self.t = time.time()


# A registery (in-memory database) of all human faces that are currently
# visible, or have been recently seen.  Implements various basic look-at
# actions, including:
# *) turning to face a given face
# *) tracking a face with the eyes
# *) glancing a currrently-visible face, or a face that was recently
#    seen.
#
# Provides the new-face, lost-face data to general-behavior, by putting
# the face data into the owyl blackboard.
class FaceTrack:

	def __init__(self, owyl_bboard):

		print("Starting Face Tracker")
		self.blackboard = owyl_bboard

		# List of currently visible faces
		self.visible_faces = []
		# List of locations of currently visible faces
		self.face_locations = {}

		# List of no longer visible faces, but seen recently.
		self.recent_locations = {}
		# How long to keep around a recently seen, but now lost face.
		self.RECENT_INTERVAL = 5

		# Current look-at-target
		self.look_at = 0
		self.gaze_at = 0
		self.glance_at = 0
		self.first_glance = -1
		self.glance_howlong = -1

		# How often we update the look-at target.
		self.LOOKAT_INTERVAL = 1
		self.last_lookat = 0

		# Last time that the list of active faces was vacuumed out.
		self.last_vacuum = 0
		self.VACUUM_INTERVAL = 1

		# Subscribed pi_vision topics and events
		self.TOPIC_FACE_EVENT = "/camera/face_event"
		self.EVENT_NEW_FACE = "new_face"
		self.EVENT_LOST_FACE = "lost_face"

		self.TOPIC_FACE_LOCATIONS = "/camera/face_locations"

		# Published blender_api topics
		self.TOPIC_FACE_TARGET = "/blender_api/set_face_target"
		self.TOPIC_GAZE_TARGET = "/blender_api/set_gaze_target"

		# Face appearance/disappearance from pi_vision
		rospy.Subscriber(self.TOPIC_FACE_EVENT, FaceEvent, self.face_event_cb)

		# Face location information from pi_vision
		rospy.Subscriber(self.TOPIC_FACE_LOCATIONS, Faces, self.face_loc_cb)

		# Where to look
		self.look_pub = rospy.Publisher(self.TOPIC_FACE_TARGET, \
			Target, queue_size=10)

		self.gaze_pub = rospy.Publisher(self.TOPIC_GAZE_TARGET, \
			Target, queue_size=10)

	# ---------------------------------------------------------------
	# Public API. Use these to get things done.

	# Turn only the eyes towards the given target face; track that face.
	def gaze_at_face(self, faceid):
		print ("gaze at: " + str(faceid))

		# Look at neutral position, 1 meter in front
		if 0 == faceid :
			trg = Target()
			trg.x = 1.0
			trg.y = 0.0
			trg.z = 0.0
			self.gaze_pub.publish(trg)

		self.last_lookat = 0
		if faceid not in self.visible_faces :
			self.gaze_at = 0
			return

		self.gaze_at = faceid

	# Turn entire head to look at the given target face. The head-turn is
	# performed only once per call; after that, the eyes will then
	# automatically track that face, but the head will not.  Call again,
	# to make the head move again.
	#
	def look_at_face(self, faceid):
		print ("look at: " + str(faceid))

		# Look at neutral position, 1 meter in front
		if 0 == faceid :
			trg = Target()
			trg.x = 1.0
			trg.y = 0.0
			trg.z = 0.0
			self.look_pub.publish(trg)

		self.last_lookat = 0
		if faceid not in self.visible_faces :
			self.look_at = 0
			return

		self.look_at = faceid

	def glance_at_face(self, faceid, howlong):
		print("glance at: " + str(faceid) + " for " + str(howlong) + " seconds")
		self.glance_at = faceid
		self.glance_howlong = howlong
		self.first_glance = -1

	# ---------------------------------------------------------------
	# Private functions, not for use outside of this class.
	# Add a face to the Owyl blackboard.
	def add_face_to_bb(self, faceid):

		# We already know about it.
		if faceid in self.blackboard["background_face_targets"]:
			return

		# Update the blackboard.
		self.blackboard["is_interruption"] = True
		self.blackboard["new_face"] = faceid
		self.blackboard["background_face_targets"].append(faceid)

	# Remove a face from the Owyl blackboard.
	def remove_face_from_bb(self, fid):

		if fid not in self.blackboard["background_face_targets"]:
			return

		# Update the blackboard.
		self.blackboard["is_interruption"] = True
		self.blackboard["lost_face"] = fid
		self.blackboard["background_face_targets"].remove(fid)
		# If the robot lost the new face during the initial
		# interaction, reset new_face variable
		if self.blackboard["new_face"] == fid :
			self.blackboard["new_face"] = ""

	# Start tracking a face
	def add_face(self, faceid):
		if faceid in self.visible_faces:
			return

		self.visible_faces.append(faceid)

		print "New face added to visibile faces: " + \
			str(self.face_locations.keys())

		self.add_face_to_bb(faceid)

	# Stop tracking a face
	def remove_face(self, faceid):
		self.remove_face_from_bb(faceid)
		if faceid in self.visible_faces:
			self.visible_faces.remove(faceid)

		if faceid in self.face_locations:
			del self.face_locations[faceid]

		# print "Lost face; visibile faces now: " + str(self.visible_faces))
		print "Lost face; visibile faces now: " + \
			str(self.face_locations.keys())


	# ----------------------------------------------------------
	# Main look-at action driver.  Should be called at least a few times
	# per second.  This publishes all of the eye-related actions that the
	# blender api robot head should be performing.
	#
	# This performs multiple actions:
	# 1) updates the list of currently visible faces
	# 2) updates the list of recently seen (but now lost) faces
	# 3) If we should be looking at one of these faces, then look
	#    at it, now.
	def do_look_at_actions(self) :
		now = time.time()

		# Should we be glancing elsewhere? If so, then do it, and
		# do it actively, i.e. track that face intently.
		if 0 < self.glance_at:
			if self.first_glance < 0:
				self.first_glance = now
			if (now - self.first_glance < self.glance_howlong):
				face = None

				# If not a currently visible face, then maybe it was visible
				# recently.
				if self.glance_at in self.face_locations.keys() :
					face = self.face_locations[self.glance_at]
				elif self.glance_at in self.recent_locations.keys() :
					face = self.recent_locations[self.glance_at]

				if face:
					trg = Target()
					trg.x = face.x
					trg.y = face.y
					trg.z = face.z
					self.gaze_pub.publish(trg)
				else :
					print("Error: no face to glance at!")
					self.glance_at = 0
					self.first_flance = -1

			else :
				# We are done with the glance. Resume normal operations.
				self.glance_at = 0
				self.first_glance = -1

		# Publish a new lookat target to the blender API
		elif (now - self.last_lookat > self.LOOKAT_INTERVAL):
			self.last_lookat = now

			# Update the eye position, if need be. Skip, if there
			# is also a pending look-at to perform.
			if 0 < self.gaze_at and self.look_at <= 0:
				print("Gaze at id " + str(self.gaze_at))
				try:
					face = self.face_locations[self.gaze_at]
				except KeyError:
					print("Error: no gaze-at target")
					self.gaze_at_face(0)
					return
				trg = Target()
				trg.x = face.x
				trg.y = face.y
				trg.z = face.z
				self.gaze_pub.publish(trg)

			if 0 < self.look_at:
				print("Look at id " + str(self.look_at))
				try:
					face = self.face_locations[self.look_at]
				except KeyError:
					print("Error: no look-at target")
					self.look_at_face(0)
					return
				trg = Target()
				trg.x = face.x
				trg.y = face.y
				trg.z = face.z
				self.look_pub.publish(trg)

				# Now that we've turned to face the target, don't do it
				# again; instead, just track with the eyes.
				self.gaze_at = self.look_at
				self.look_at = -1

		# General housecleaning.
		# If the location of a face has not been reported in a while,
		# remove it from the active list, and put it on the recently-seen
		# list. We should have gotten a lost face message for this,
		# but these do not always seem reliable.
		if (now - self.last_vacuum > self.VACUUM_INTERVAL):
			self.last_vacuum = now
			for fid in self.face_locations.keys():
				face = self.face_locations[fid]
				if (now - face.t > self.VACUUM_INTERVAL):
					self.recent_locations[fid] = self.face_locations[fid]
					del self.face_locations[fid]

			# Vacuum out the recent locations as well.
			for fid in self.recent_locations.keys():
				face = self.recent_locations[fid]
				if (now - face.t > self.RECENT_INTERVAL):
					del self.recent_locations[fid]


	# ----------------------------------------------------------
	# pi_vision ROS callbacks

	# pi_vision ROS callback, called when a new face is detected,
	# or a face is lost.  Note: I don't think this is really needed,
	# the face_loc_cb accomplishes the same thing. So maybe should
	# remove this someday.
	def face_event_cb(self, data):
		if data.face_event == self.EVENT_NEW_FACE:
			self.add_face(data.face_id)

		elif data.face_event == self.EVENT_LOST_FACE:
			self.remove_face(data.face_id)

	# pi_vision ROS callback, called when pi_vision has new face
	# location data for us. Because this happens frequently (10x/second)
	# we also use this as the main update loop, and drive all look-at
	# actions from here.
	def face_loc_cb(self, data):
		for face in data.faces:
			fid = face.id
			loc = face.point
			inface = Face(fid, loc)

			# Sanity check.  Sometimes pi_vision sends us faces with
			# location (0,0,0). Discard these.
			if loc.x < 0.05:
				continue

			self.add_face(fid)
			self.face_locations[fid] = inface

			# If we see it now, its not 'recently seen' any longer.
			if fid in self.recent_locations:
				del self.recent_locations[fid]

		# Now perform all the various looking-at actions
		self.do_look_at_actions()
