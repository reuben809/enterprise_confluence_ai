"""
Feedback storage module for persisting user feedback to MongoDB.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional
from pymongo import MongoClient, DESCENDING
from pymongo.collection import Collection

from config.settings import settings

logger = logging.getLogger(__name__)


class FeedbackStore:
    """Stores and retrieves user feedback from MongoDB."""
    
    COLLECTION_NAME = "feedback"
    
    def __init__(self, mongo_uri: str = None, db_name: str = None):
        """Initialize MongoDB connection for feedback storage."""
        self.mongo_uri = mongo_uri or settings.mongo_uri
        self.db_name = db_name or settings.mongo_db
        self._client: Optional[MongoClient] = None
        self._collection: Optional[Collection] = None
    
    @property
    def collection(self) -> Collection:
        """Lazy initialization of MongoDB collection."""
        if self._collection is None:
            self._client = MongoClient(self.mongo_uri)
            db = self._client[self.db_name]
            self._collection = db[self.COLLECTION_NAME]
            # Create indexes for common queries
            self._collection.create_index([("created_at", DESCENDING)])
            self._collection.create_index("feedback_type")
            logger.info(f"✅ Connected to MongoDB feedback collection: {self.db_name}.{self.COLLECTION_NAME}")
        return self._collection
    
    def save_feedback(
        self,
        question: str,
        answer: str,
        sources: List[dict],
        feedback_type: str,
        user_id: Optional[str] = None,
        comment: Optional[str] = None
    ) -> str:
        """
        Save user feedback to MongoDB.
        
        Args:
            question: The user's original question
            answer: The generated answer
            sources: List of source documents used
            feedback_type: 'positive' or 'negative'
            user_id: Optional user identifier
            comment: Optional additional user comment
            
        Returns:
            The inserted document's ID as a string
        """
        doc = {
            "question": question,
            "answer": answer,
            "sources": sources,
            "feedback_type": feedback_type,
            "user_id": user_id,
            "comment": comment,
            "created_at": datetime.now(timezone.utc),
        }
        
        result = self.collection.insert_one(doc)
        logger.info(f"Feedback saved with ID: {result.inserted_id}")
        return str(result.inserted_id)
    
    def get_feedback_stats(self) -> dict:
        """Get aggregated feedback statistics."""
        pipeline = [
            {
                "$group": {
                    "_id": "$feedback_type",
                    "count": {"$sum": 1}
                }
            }
        ]
        results = list(self.collection.aggregate(pipeline))
        stats = {r["_id"]: r["count"] for r in results}
        stats["total"] = sum(stats.values())
        return stats
    
    def get_recent_feedback(self, limit: int = 50, feedback_type: Optional[str] = None) -> List[dict]:
        """
        Retrieve recent feedback entries.
        
        Args:
            limit: Maximum number of entries to return
            feedback_type: Optional filter for 'positive' or 'negative'
            
        Returns:
            List of feedback documents
        """
        query = {}
        if feedback_type:
            query["feedback_type"] = feedback_type
            
        cursor = self.collection.find(query).sort("created_at", DESCENDING).limit(limit)
        
        results = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])  # Convert ObjectId to string
            results.append(doc)
        return results
    
    def get_negative_feedback_for_review(self, limit: int = 20) -> List[dict]:
        """Get negative feedback entries for quality review."""
        return self.get_recent_feedback(limit=limit, feedback_type="negative")
    
    def close(self):
        """Close the MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._collection = None


# Singleton instance for use across the app
feedback_store = FeedbackStore()
